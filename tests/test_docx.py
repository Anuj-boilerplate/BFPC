"""Tests for the DocX reader."""

from __future__ import annotations

from pathlib import Path

import pytest

from bfpc.parser.docx_reader import DocxReader
from bfpc.parser.models import BlockKind, Source


@pytest.fixture()
def reader() -> DocxReader:
    return DocxReader()


def test_reads_docx_structure(docx_file: Path, reader: DocxReader) -> None:
    document = reader.read(docx_file)

    assert document.source == Source.DOCX
    assert document.page_count == 1
    kinds = [block.kind for block in document.pages[0].blocks]
    assert BlockKind.HEADING in kinds
    assert BlockKind.TABLE in kinds


def test_heading_detection(docx_file: Path, reader: DocxReader) -> None:
    document = reader.read(docx_file)
    headings = [b.text for b in document.pages[0].blocks if b.kind == BlockKind.HEADING]
    assert "DocX Report" in headings
    assert "Data" in headings


def test_table_serialization(docx_file: Path, reader: DocxReader) -> None:
    document = reader.read(docx_file)
    tables = [b for b in document.pages[0].blocks if b.kind == BlockKind.TABLE]
    assert len(tables) == 1
    assert "Alpha | 42" in tables[0].text


def test_body_order_preserved(docx_file: Path, reader: DocxReader) -> None:
    document = reader.read(docx_file)
    blocks = document.pages[0].blocks
    texts = [b.text for b in blocks]
    assert texts.index("DocX Report") < texts.index("Data") < texts.index("A trailing paragraph.")


def test_invalid_file_raises(reader: DocxReader, tmp_path: Path) -> None:
    bogus = tmp_path / "bogus.docx"
    bogus.write_text("not a zip file", encoding="utf-8")
    with pytest.raises(ValueError):
        reader.read(bogus)


def test_missing_file_raises(reader: DocxReader, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        reader.read(tmp_path / "does_not_exist.docx")
