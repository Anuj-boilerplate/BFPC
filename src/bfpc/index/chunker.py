"""Chunking layer: turns parsed documents into retrievable chunks.

A :class:`Chunker` is any callable that maps a parsed
:class:`~bfpc.parser.models.Document` to a list of :class:`Chunk`
objects. Strategies register themselves under a stable name so the
evaluation harness can select them with ``--chunker <name>``.

The ~500-token ceiling encoded in :data:`MAX_CHUNK_CHARS` is a design
consensus, not a hard law: a strategy may choose a different cap, but
should stay under the embedding model's context window with room to
spare.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from bfpc.parser.models import Document

#: Rough ~500-token ceiling for a single chunk (avg ~4 chars/token).
MAX_CHUNK_CHARS = 2000

#: Chunkers by stable name, populated via :func:`register`.
REGISTRY: dict[str, Callable[[Document], list[Chunk]]] = {}


@dataclass(slots=True)
class Chunk:
    """A retrievable unit of document text with provenance for highlighting.

    ``bbox`` is ``None`` for sources without coordinates (Markdown, DocX)
    and for strategies that do not track per-chunk regions.
    """

    id: str
    text: str
    page: int
    source: str
    bbox: tuple[float, float, float, float] | None = None
    kind: str = "text"

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("chunk id must not be empty")
        if self.page < 1:
            raise ValueError(f"chunk page must be 1-based, got {self.page}")
        if not self.text.strip():
            raise ValueError(f"chunk {self.id!r} has no text")


def register(name: str) -> Callable[[Chunker], Chunker]:
    """Register a chunking strategy under ``name`` (idempotency is not allowed)."""

    def decorator(fn: Chunker) -> Chunker:
        if name in REGISTRY:
            raise ValueError(f"chunker {name!r} is already registered")
        REGISTRY[name] = fn
        return fn

    return decorator


class Chunker(Protocol):
    """Any strategy that maps a parsed document to chunks."""

    def __call__(self, document: Document) -> list[Chunk]: ...
