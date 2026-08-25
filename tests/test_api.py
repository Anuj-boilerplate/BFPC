"""Contract conformance tests for the HTTP API (docs/api.md §8).

Uses a deterministic fake embedder (no model download) so retrieval
ordering is stable and reproducible. A small PDF and a Markdown file are
generated on the fly as upload fixtures.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pymupdf
import pytest
from fastapi.testclient import TestClient

from bfpc.api.app import create_app
from bfpc.api.service import IndexService

_DIM = 64


class FakeEmbedder:
    """Hash-based content embedding: identical texts -> identical vectors."""

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._vector(t) for t in texts]).astype(np.float32)

    def embed_query(self, query: str) -> np.ndarray:
        q = re.sub(r"^search_query:\s*", "", query)
        return self._vector(q).astype(np.float32)

    def _vector(self, text: str) -> np.ndarray:
        vec = np.zeros(_DIM, dtype=np.float64)
        for token in re.findall(r"\w+", text.lower()):
            vec[hash(token) % _DIM] += 1.0
        norm = np.linalg.norm(vec)
        return vec / norm if norm else np.zeros(_DIM, dtype=np.float64)


@pytest.fixture()
def client() -> TestClient:
    service = IndexService(FakeEmbedder())
    return TestClient(create_app(service))


@pytest.fixture()
def md_bytes() -> bytes:
    return (
        "# Title\n\n"
        "The parser uses PyMuPDF for extraction.\n\n"
        "- item one\n"
        "- item two\n\n"
        "INT8 latency is 18.48 ms on page 12.\n"
    ).encode("utf-8")


@pytest.fixture()
def pdf_bytes() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((20, 40), "Report title", fontsize=18)
    page.insert_text((20, 80), "INT8 static quantization latency is 18.48 ms.")
    page.insert_text((20, 120), "FP16 runtime uses a CUDA backend.")
    buf = doc.tobytes()
    doc.close()
    return buf


def _upload(client: TestClient, name: str, payload: bytes) -> None:
    response = client.post(
        "/api/index",
        files={"file": (name, payload)},
    )
    assert response.status_code == 200, response.text


def _post_json(client: TestClient, path: str, body: dict):
    return client.post(path, json=body)


class TestStatus:
    def test_unindexed_status_shape(self, client: TestClient) -> None:
        response = client.get("/api/status")
        assert response.status_code == 200
        assert response.json() == {
            "indexed": False,
            "filename": None,
            "source": None,
            "pages": None,
            "chunks": None,
        }

    def test_indexed_status_shape(self, client: TestClient, md_bytes: bytes) -> None:
        _upload(client, "sample.md", md_bytes)
        response = client.get("/api/status")
        assert response.status_code == 200
        body = response.json()
        assert body["indexed"] is True
        assert body["filename"] == "sample.md"
        assert body["source"] == "markdown"


class TestIndex:
    def test_index_response_shape(self, client: TestClient, md_bytes: bytes) -> None:
        _upload(client, "sample.md", md_bytes)
        # captured by _upload's 200; re-assert exact body here
        response = client.post("/api/index", files={"file": ("x.md", md_bytes)})
        body = response.json()
        assert set(body) == {"filename", "source", "pages", "chunks", "kinds"}
        assert body["filename"] == "x.md"
        assert body["source"] == "markdown"
        assert body["pages"] == 1
        assert body["chunks"] >= 1
        assert set(body["kinds"]) == {"text", "table", "heading", "list"}
        assert sum(body["kinds"].values()) == body["chunks"]

    def test_unsupported_extension_400(self, client: TestClient, md_bytes: bytes) -> None:
        response = client.post("/api/index", files={"file": ("notes.txt", md_bytes)})
        assert response.status_code == 400
        assert set(response.json()) == {"detail"}

    def test_empty_upload_422(self, client: TestClient) -> None:
        response = client.post("/api/index", files={"file": ("blank.md", b"")})
        assert response.status_code == 422  # empty body rejected by endpoint

    def test_missing_file_part_422(self, client: TestClient) -> None:
        response = client.post("/api/index", data={"other": "x"})
        assert response.status_code == 422

    def test_extra_form_field_422(self, client: TestClient, md_bytes: bytes) -> None:
        response = client.post(
            "/api/index",
            data={"extras": "nope"},
            files={"file": ("sample.md", md_bytes)},
        )
        assert response.status_code == 422

    def test_reindex_replaces_previous(self, client: TestClient, md_bytes: bytes, pdf_bytes: bytes) -> None:
        _upload(client, "a.md", md_bytes)
        _upload(client, "b.pdf", pdf_bytes)
        status = client.get("/api/status").json()
        assert status["source"] == "pdf"
        assert status["filename"] == "b.pdf"

    def test_failed_reindex_leaves_previous_untouched(self, client: TestClient, md_bytes: bytes) -> None:
        _upload(client, "a.md", md_bytes)
        before = client.get("/api/status").json()
        # Whitespace-only markdown parses to zero chunks -> 400, no state change.
        response = client.post("/api/index", files={"file": ("blank.md", b"   \n\n\t")})
        assert response.status_code == 400
        after = client.get("/api/status").json()
        assert after == before


class TestSearch:
    def test_search_before_any_index_409(self, client: TestClient) -> None:
        response = _post_json(client, "/api/search", {"query": "anything"})
        assert response.status_code == 409
        assert set(response.json()) == {"detail"}

    def test_hits_shape_and_ordering(self, client: TestClient, md_bytes: bytes) -> None:
        _upload(client, "sample.md", md_bytes)
        response = client.post("/api/search", json={"query": "INT8 latency", "top_k": 3})
        assert response.status_code == 200
        body = response.json()
        assert body["query"] == "INT8 latency"
        assert body["top_k"] == 3
        assert 1 <= len(body["hits"]) <= 3
        scores = [h["score"] for h in body["hits"]]
        assert scores == sorted(scores, reverse=True)
        for hit in body["hits"]:
            assert set(hit) == {"chunk_id", "text", "page", "kind", "score", "bbox", "snippet", "rects"}
            assert hit["page"] >= 1
            assert hit["kind"] in {"text", "table", "heading", "list"}
            assert isinstance(hit["score"], float)
        # The factoid line is the best match and carries a real bbox.
        top = body["hits"][0]
        assert "INT8" in top["text"]
        assert top["bbox"] is None  # markdown -> null bbox (contract §5.4)
        assert top["snippet"] is None  # markdown -> no sentence localization
        assert top["rects"] is None

    def test_pdf_bbox_is_non_null(self, client: TestClient, pdf_bytes: bytes) -> None:
        _upload(client, "report.pdf", pdf_bytes)
        body = client.post("/api/search", json={"query": "INT8 latency"}).json()
        assert body["hits"][0]["bbox"] is not None
        x0, y0, x1, y1 = body["hits"][0]["bbox"]
        assert x0 <= x1
        assert y0 <= y1

    def test_pdf_sentence_localization(self, client: TestClient, pdf_bytes: bytes) -> None:
        _upload(client, "report.pdf", pdf_bytes)
        body = client.post("/api/search", json={"query": "INT8 latency"}).json()
        top = body["hits"][0]
        # The snippet is the best-matching sentence, not the whole block.
        assert top["snippet"] is not None
        assert top["snippet"] in top["text"]
        # Rectangles wrap tightly around the sentence on the page.
        assert top["rects"] is not None
        assert len(top["rects"]) >= 1
        for rect in top["rects"]:
            assert len(rect) == 4
            rx0, ry0, rx1, ry1 = rect
            assert rx0 <= rx1
            assert ry0 <= ry1

    def test_blank_query_422(self, client: TestClient, md_bytes: bytes) -> None:
        _upload(client, "sample.md", md_bytes)
        response = _post_json(client, "/api/search", {"query": "   "})
        assert response.status_code == 422
        assert set(response.json()) == {"detail"}

    def test_top_k_out_of_range_422(self, client: TestClient, md_bytes: bytes) -> None:
        _upload(client, "sample.md", md_bytes)
        assert _post_json(client, "/api/search", {"query": "x", "top_k": 0}).status_code == 422
        assert _post_json(client, "/api/search", {"query": "x", "top_k": 21}).status_code == 422

    def test_unknown_field_422(self, client: TestClient, md_bytes: bytes) -> None:
        _upload(client, "sample.md", md_bytes)
        response = _post_json(client, "/api/search", {"query": "x", "top_k": 5, "extra": 1})
        assert response.status_code == 422

    def test_malformed_json_422(self, client: TestClient, md_bytes: bytes) -> None:
        _upload(client, "sample.md", md_bytes)
        response = client.post("/api/search", content=b"{not json", headers={"Content-Type": "application/json"})
        assert response.status_code == 422

    def test_top_k_clamped_to_chunk_count(self, client: TestClient, md_bytes: bytes) -> None:
        _upload(client, "sample.md", md_bytes)
        n_chunks = client.get("/api/status").json()["chunks"]
        body = client.post("/api/search", json={"query": "x", "top_k": n_chunks * 2}).json()
        assert len(body["hits"]) == n_chunks  # clamped, still cites requested top_k
        assert body["top_k"] == n_chunks * 2


class TestDocument:
    def test_document_before_any_index_409(self, client: TestClient) -> None:
        response = client.get("/api/document")
        assert response.status_code == 409

    def test_document_returns_uploaded_bytes(self, client: TestClient, pdf_bytes: bytes) -> None:
        _upload(client, "report.pdf", pdf_bytes)
        response = client.get("/api/document")
        assert response.status_code == 200
        assert response.content == pdf_bytes
        assert response.headers["content-type"] == "application/pdf"
        assert 'filename="report.pdf"' in response.headers["content-disposition"]

    def test_document_markdown_content_type(self, client: TestClient, md_bytes: bytes) -> None:
        _upload(client, "sample.md", md_bytes)
        response = client.get("/api/document")
        assert response.headers["content-type"] == "text/markdown"


class TestRobustness:
    """Error-path behavior: failures must never disturb the active document."""

    def test_corrupt_pdf_500_preserves_previous(self, client: TestClient, md_bytes: bytes) -> None:
        _upload(client, "a.md", md_bytes)
        before = client.get("/api/status").json()
        response = client.post("/api/index", files={"file": ("broken.pdf", b"this is not a pdf")})
        assert response.status_code == 500
        assert client.get("/api/status").json() == before

    def test_non_utf8_markdown_500_preserves_previous(self, client: TestClient, md_bytes: bytes) -> None:
        _upload(client, "a.md", md_bytes)
        before = client.get("/api/status").json()
        response = client.post("/api/index", files={"file": ("bad.md", b"\xff\xfe\xfa not utf-8")})
        assert response.status_code == 500
        assert client.get("/api/status").json() == before

    def test_oversize_upload_422(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        # importlib: `import bfpc.api.app as m` would bind the package-level
        # `app` attribute (the FastAPI instance) instead of the module.
        import importlib

        app_module = importlib.import_module("bfpc.api.app")
        monkeypatch.setattr(app_module, "MAX_UPLOAD_BYTES", 16)
        response = client.post("/api/index", files={"file": ("big.md", b"x" * 32)})
        assert response.status_code == 422
        assert set(response.json()) == {"detail"}


class _IncompleteHitService(IndexService):
    """Search stub whose hits are missing a required §5.2 field."""

    def search(self, query: str, top_k: int) -> dict:
        return {
            "query": query,
            "top_k": top_k,
            "hits": [
                {
                    "chunk_id": "1-0",
                    "text": "x",
                    "page": 1,
                    # "kind" deliberately absent
                    "score": 0.5,
                    "bbox": None,
                    "snippet": None,
                    "rects": None,
                }
            ],
        }


class TestHitSchemaFreeze:
    """Retrieval output missing any §5.2 field must be rejected (500)."""

    def test_hit_missing_field_is_rejected(self) -> None:
        service = _IncompleteHitService(FakeEmbedder())
        client = TestClient(create_app(service), raise_server_exceptions=False)
        response = client.post("/api/search", json={"query": "x", "top_k": 5})
        assert response.status_code == 500
        assert response.json() == {"detail": "internal error"}