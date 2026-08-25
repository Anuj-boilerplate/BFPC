"""IndexService: owns the single active document and the vector index.

State is replaced atomically: a fresh index is built from scratch and only
swapped into ``self._state`` after it fully succeeds, so a failed
``POST /api/index`` never disturbs the previously indexed document
(contract §2.1).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from bfpc.index.chunker import REGISTRY
from bfpc.index.index import VectorIndex
from bfpc.parser.cli import parse_document
from bfpc.parser.models import Document

# Importing the chunkers package runs auto-discovery, registering every
# strategy (including "block") into REGISTRY before first use.
from bfpc.index import chunkers as _chunkers  # noqa: F401

#: Extensions -> contract ``source`` values (contract §3.1).
_EXTENSIONS: dict[str, str] = {
    ".pdf": "pdf",
    ".md": "markdown",
    ".markdown": "markdown",
    ".docx": "docx",
}

#: ``source`` -> ``Content-Type`` for GET /api/document (contract §6.1).
_CONTENT_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "markdown": "text/markdown",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

#: Chunker registered name (contract §7).
CHUNKER_NAME = "block"


class ApiError(Exception):
    """Base class for expected, contract-mapped API errors."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NoActiveDocument(ApiError):
    """Raised when search/document is requested before any successful index."""


class UnsupportedExtension(ApiError):
    """Raised when the uploaded filename's extension is not supported."""


class ZeroChunks(ApiError):
    """Raised when a document parses to zero chunks (contract §3.3)."""


class IndexFailed(ApiError):
    """Raised when parsing/embedding/indexing fails (maps to 500)."""


@dataclass(slots=True)
class IndexState:
    """Everything the API serves about the active document."""

    filename: str
    source: str
    pages: int
    chunks: list  # list[Chunk]
    kinds: dict[str, int]
    raw: bytes
    index: VectorIndex


class IndexService:
    """Single-active-document orchestrator over chunk/embed/index/search."""

    def __init__(self, embedder, pipeline=None) -> None:
        self._embedder = embedder
        self._state: IndexState | None = None
        # Lazily created AnswerPipeline (Phase 10); injectable for tests
        self._pipeline = pipeline

    # -- queries -----------------------------------------------------------

    def status(self) -> dict:
        """Return the contract §4 status body (always succeeds)."""
        if self._state is None:
            return {"indexed": False, "filename": None, "source": None, "pages": None, "chunks": None}
        return {
            "indexed": True,
            "filename": self._state.filename,
            "source": self._state.source,
            "pages": self._state.pages,
            "chunks": len(self._state.chunks),
        }

    def search(self, query: str, top_k: int) -> dict:
        """Run a vector search over the active document (contract §5).

        PDF hits are post-processed to locate the best-matching sentence:
        the sentence ranker picks the tightest snippet from the chunk and
        the rect locator resolves it to exact page rectangles. Localization
        is best-effort — any failure degrades to ``snippet=None, rects=None``
        so retrieval never breaks.
        """
        state = self._state
        if state is None:
            raise NoActiveDocument("no document indexed yet")
        vector = self._embedder.embed_query(query)
        hits = state.index.search(vector, k=top_k)
        results = []
        for hit in hits:
            results.append(
                {
                    "chunk_id": hit.chunk.id,
                    "text": hit.chunk.text,
                    "page": hit.chunk.page,
                    "kind": hit.chunk.kind,
                    "score": hit.score,
                    "bbox": list(hit.chunk.bbox) if hit.chunk.bbox is not None else None,
                    "snippet": None,
                    "rects": None,
                }
                | self._locate(hit, query, state)
            )
        return {"query": query, "top_k": top_k, "hits": results}

    def answer(self, query: str) -> dict:
        """Run the full answer pipeline over the active document (Phase 10/11)."""
        state = self._state
        if state is None:
            raise NoActiveDocument("no document indexed yet")
        # Lazily create pipeline if not injected (tests may inject mock)
        if self._pipeline is None:
            from bfpc.context.factory import create_generator
            from bfpc.context.pipeline import AnswerPipeline

            try:
                generator = create_generator()
            except Exception as exc:
                raise IndexFailed(f"failed to create generator: {exc}") from exc
            self._pipeline = AnswerPipeline(retriever=self, generator=generator)

        trail_report = self._pipeline.answer(query)
        result = trail_report.result
        # Retrieve the LLMContext used for the last pipeline call
        context = getattr(self._pipeline, "_last_context", None)
        if context is None:
            context = getattr(self._pipeline, "_context_last", None)
        if context is None:
            from bfpc.context.builder import ContextBuilder

            context = ContextBuilder().build([])

        from bfpc.context.trail_builder import build_trail

        # Only PDF has highlightable rects; non-PDF yields [] via trail_builder
        pdf_bytes = state.raw if state.source == "pdf" else None
        trail = build_trail(result, context, pdf_bytes)

        status = "COMPLETE" if trail_report.report.complete else "INSUFFICIENT_EVIDENCE"
        return {
            "query": query,
            "answer": result.answer,
            "status": status,
            "missing": result.missing,
            "trail": [
                {
                    "source_id": item.source_id,
                    "label": item.label,
                    "explanation": item.explanation,
                    "page": item.page,
                    "rects": item.rects,
                }
                for item in trail.items
            ],
        }

    @staticmethod
    def _locate(hit, query: str, state: IndexState) -> dict:
        """Resolve a PDF hit to its best sentence and tight rectangles.

        Only PDF chunks with coordinates are localized; other sources have
        nothing to search for. Lazy imports keep module load cheap.
        """
        if state.source != "pdf" or hit.chunk.bbox is None:
            return {}
        try:
            from bfpc.index.locator import locate_text, locate_words
            from bfpc.index.sentence_ranker import rank_sentences

            ranked = rank_sentences(query, hit.chunk.text, top_n=1)
            if not ranked:
                return {}
            snippet = ranked[0]
            rects_raw = locate_words(state.raw, hit.chunk.page, snippet)
            if not rects_raw:
                rects_raw = locate_text(state.raw, hit.chunk.page, snippet)
            return {"snippet": snippet, "rects": [list(r) for r in rects_raw] if rects_raw else None}
        except Exception:
            return {}

    def document(self) -> tuple[bytes, str, str]:
        """Return ``(raw bytes, content_type, filename)`` of the active doc."""
        state = self._state
        if state is None:
            raise NoActiveDocument("no document indexed yet")
        return state.raw, _CONTENT_TYPES[state.source], state.filename

    # -- mutations ---------------------------------------------------------

    def index(self, contents: bytes, filename: str) -> dict:
        """Parse, chunk, embed and index ``contents`` as the new active doc.

        :raises UnsupportedExtension: for unknown filename extensions.
        :raises ZeroChunks: when the document produces no chunks.
        :raises IndexFailed: on any parse/embed/index failure.
        """
        extension = Path(filename).suffix.lower()
        source = _EXTENSIONS.get(extension)
        if source is None:
            supported = ", ".join(sorted(_EXTENSIONS))
            raise UnsupportedExtension(f"Unsupported file type '{extension}'. Supported: {supported}")

        try:
            document = self._parse(contents, extension)
            chunks = self._chunk(document)
            if not chunks:
                raise ZeroChunks("document contains no chunkable content")
            state = self._build_state(contents, filename, source, document, chunks)
        except ZeroChunks:
            raise
        except Exception as exc:
            raise IndexFailed(f"indexing failed: {exc}") from exc

        self._state = state
        return self._index_response(state)

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _parse(contents: bytes, extension: str) -> Document:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / f"upload{extension}"
            path.write_bytes(contents)
            return parse_document(path)

    def _chunk(self, document: Document) -> list:
        return REGISTRY[CHUNKER_NAME](document)

    def _build_state(
        self,
        contents: bytes,
        filename: str,
        source: str,
        document: Document,
        chunks: Sequence,
    ) -> IndexState:
        vectors = self._embedder.embed_documents([c.text for c in chunks])
        index = VectorIndex()
        index.add(list(chunks), vectors)
        return IndexState(
            filename=filename,
            source=source,
            pages=len(document.pages),
            chunks=list(chunks),
            kinds=_kind_counts(chunks),
            raw=contents,
            index=index,
        )

    @staticmethod
    def _index_response(state: IndexState) -> dict:
        return {
            "filename": state.filename,
            "source": state.source,
            "pages": state.pages,
            "chunks": len(state.chunks),
            "kinds": dict(state.kinds),
        }


def _kind_counts(chunks: Sequence) -> dict[str, int]:
    """Always report exactly text/table/heading/list (contract §3.2)."""
    counter = Counter(getattr(c, "kind", "text") for c in chunks)
    return {kind: counter.get(kind, 0) for kind in ("text", "table", "heading", "list")}
