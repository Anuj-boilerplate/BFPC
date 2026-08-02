"""Tests for the PDF reader."""

from __future__ import annotations

from pathlib import Path

import pytest

from bfpc.parser.models import BlockKind, Source
from bfpc.parser.pdf_reader import PdfReader


@pytest.fixture()
def reader() -> PdfReader:
    return PdfReader()


def test_reads_multiple_pages(multi_page_pdf: Path, reader: PdfReader) -> None:
    document = reader.read(multi_page_pdf)

    assert document.source == Source.PDF
    assert document.page_count == 3
    assert document.metadata["page_count"] == 3


def test_blocks_have_bbox(multi_page_pdf: Path, reader: PdfReader) -> None:
    document = reader.read(multi_page_pdf)
    text_blocks = [b for page in document.pages for b in page.blocks if b.kind == BlockKind.TEXT]
    assert text_blocks
    assert all(b.bbox is not None for b in text_blocks)


def test_heading_detection(multi_page_pdf: Path, reader: PdfReader) -> None:
    document = reader.read(multi_page_pdf)
    headings = [b for page in document.pages for b in page.blocks if b.kind == BlockKind.HEADING]
    assert len(headings) >= 3  # one per page
    assert any("Heading" in h.text for h in headings)


def test_blank_page_preserved(empty_page_pdf: Path, reader: PdfReader) -> None:
    document = reader.read(empty_page_pdf)

    assert document.page_count == 2
    assert document.pages[0].blocks  # content page
    assert document.pages[1].blocks == []  # blank page kept, no blocks


def test_invalid_file_raises(reader: PdfReader, tmp_path: Path) -> None:
    bogus = tmp_path / "bogus.pdf"
    bogus.write_text("this is definitely not a pdf", encoding="utf-8")
    with pytest.raises(ValueError):
        reader.read(bogus)


def test_missing_file_raises(reader: PdfReader, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        reader.read(tmp_path / "does_not_exist.pdf")
