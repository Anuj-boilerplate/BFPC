"""Core data model shared by all document readers.

The model is deliberately small: a parsed document is a list of pages,
each page a list of ordered blocks. Every block records the source that
produced it and, for PDFs, the coordinates it came from. These two fields
are the extension points: OCR output becomes a new ``Source`` value and
highlighting/search consume ``bbox``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class Source(StrEnum):
    """Which engine produced a block's text."""

    PDF = "pdf"
    MARKDOWN = "markdown"
    DOCX = "docx"


class BlockKind(StrEnum):
    """Rough semantic category of a block."""

    TEXT = "text"
    HEADING = "heading"
    LIST = "list"
    TABLE = "table"
    IMAGE = "image"


@dataclass(slots=True)
class Block:
    """A unit of text with an optional location and a provenance tag."""

    text: str
    source: Source
    kind: BlockKind = BlockKind.TEXT
    bbox: tuple[float, float, float, float] | None = None

    def __post_init__(self) -> None:
        if self.source == Source.PDF and self.bbox is None:
            raise ValueError("PDF blocks must carry a bounding box")


@dataclass(slots=True)
class Page:
    """One page of a document. Number is 1-based and never skipped."""

    number: int
    blocks: list[Block] = field(default_factory=list)


@dataclass(slots=True)
class Document:
    """A fully parsed document."""

    path: Path
    source: Source
    pages: list[Page] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def page_count(self) -> int:
        """Total number of pages, including any that parsed to zero blocks."""
        return len(self.pages)
