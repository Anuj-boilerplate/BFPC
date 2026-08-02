"""Tests for the data model invariants."""

from __future__ import annotations

import pytest

from bfpc.parser.models import Block, BlockKind, Document, Page, Source


def test_pdf_block_requires_bbox() -> None:
    with pytest.raises(ValueError):
        Block(text="x", source=Source.PDF)


def test_pdf_block_accepts_bbox() -> None:
    block = Block(text="x", source=Source.PDF, bbox=(0, 0, 10, 10))
    assert block.bbox == (0, 0, 10, 10)


def test_non_pdf_block_bbox_optional() -> None:
    block = Block(text="x", source=Source.MARKDOWN)
    assert block.bbox is None


def test_page_count_includes_empty_pages() -> None:
    document = Document(
        path="f.pdf",
        source=Source.PDF,
        pages=[Page(number=1, blocks=[Block(text="a", source=Source.PDF, bbox=(0, 0, 1, 1))]), Page(number=2)],
    )
    assert document.page_count == 2
