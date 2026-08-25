"""Unit tests for the Gemini API embedder (no network; httpx MockTransport).

Covers request assembly (batch size, taskType, dimensionality), response
parsing with L2 normalization, retry-on-429, and error propagation.
"""

from __future__ import annotations

import json

import httpx
import numpy as np
import pytest

from bfpc.index.embedder import MAX_BATCH, OUTPUT_DIMENSIONALITY, Embedder

_BASE = "https://example.test/v1beta"


def _embedder(handler: httpx.MockTransport.Handler) -> Embedder:
    return Embedder(
        api_key="test-key",
        base_url=_BASE,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _reply(values: list[list[float]]):
    return httpx.Response(200, json={"embeddings": [{"values": v} for v in values]})


class TestEmbedder:
    def test_documents_batch_payload_shape(self) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["payload"] = json.loads(request.content)
            seen["headers"] = request.headers
            return _reply([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])

        embedder = _embedder(handler)
        vectors = embedder.embed_documents(["one chunk", "two chunk"])
        assert seen["url"] == f"{_BASE}/models/gemini-embedding-001:batchEmbedContents"
        assert seen["headers"]["x-goog-api-key"] == "test-key"
        requests = seen["payload"]["requests"]
        assert len(requests) == 2
        for req in requests:
            assert req["model"] == "models/gemini-embedding-001"
            assert req["taskType"] == "RETRIEVAL_DOCUMENT"
            assert req["outputDimensionality"] == OUTPUT_DIMENSIONALITY
        assert [req["content"]["parts"][0]["text"] for req in requests] == [
            "one chunk",
            "two chunk",
        ]
        assert vectors.shape == (2, 3)
        assert vectors.dtype == np.float32

    def test_query_uses_retrieval_query_and_returns_1d(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            req = json.loads(request.content)["requests"][0]
            assert req["taskType"] == "RETRIEVAL_QUERY"
            return _reply([[0.3, 0.4]])

        vector = _embedder(handler).embed_query("latency of int8?")
        assert vector.shape == (2,)
        assert vector.dtype == np.float32

    def test_vectors_are_l2_normalized(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return _reply([[3.0, 4.0]])

        vector = _embedder(handler).embed_query("x")
        assert np.isclose(np.linalg.norm(vector), 1.0)
        assert np.isclose(vector[0], 0.6)
        assert np.isclose(vector[1], 0.8)

    def test_batches_large_corpora(self) -> None:
        counts: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            reqs = json.loads(request.content)["requests"]
            counts.append(len(reqs))
            return _reply([[0.1, 0.2]] * len(reqs))

        texts = [f"chunk {i}" for i in range(MAX_BATCH + 3)]
        vectors = _embedder(handler).embed_documents(texts)
        assert counts == [MAX_BATCH, 3]
        assert vectors.shape == (len(texts), 2)

    def test_rate_limit_retries_then_succeeds(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(429, text="quota exceeded")
            return _reply([[0.2, 0.1]])

        assert _embedder(handler).embed_query("x").shape == (2,)

    def test_hard_error_propagates(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, text="bad model")

        with pytest.raises(RuntimeError, match="400"):
            _embedder(handler).embed_query("x")

    def test_empty_corpus_returns_empty(self) -> None:
        assert Embedder(api_key="k").embed_documents([]).shape == (0, 0)
