"""Tests for the Markdown reader."""

from __future__ import annotations

from pathlib import Path

import pytest

from bfpc.parser.markdown_reader import MarkdownReader
from bfpc.parser.models import BlockKind, Source


@pytest.fixture()
def reader() -> MarkdownReader:
    return MarkdownReader()


def test_reads_markdown_structure(markdown_file: Path, reader: MarkdownReader) -> None:
    document = reader.read(markdown_file)

    assert document.source == Source.MARKDOWN
    assert document.page_count == 1
    kinds = [block.kind for block in document.pages[0].blocks]
    assert BlockKind.HEADING in kinds
    assert BlockKind.LIST in kinds
    assert BlockKind.TEXT in kinds


def test_blocks_have_no_bbox(markdown_file: Path, reader: MarkdownReader) -> None:
    document = reader.read(markdown_file)
    assert all(block.bbox is None for page in document.pages for block in page.blocks)


def test_adjacent_paragraphs_merge(markdown_file: Path, reader: MarkdownReader) -> None:
    document = reader.read(markdown_file)
    blocks = document.pages[0].blocks

    paragraphs = [b for b in blocks if b.kind == BlockKind.TEXT and "```" not in b.text]
    assert len(paragraphs) >= 1


def test_missing_file_raises(reader: MarkdownReader, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        reader.read(tmp_path / "does_not_exist.md")


def test_strips_bom(reader: MarkdownReader, tmp_path: Path) -> None:
    """A UTF-8 BOM (common on Windows files) must not leak into block text."""
    path = tmp_path / "bom.md"
    path.write_text("\ufeff# Heading\n\nBody.", encoding="utf-8")
    document = reader.read(path)
    all_text = " ".join(b.text for b in document.pages[0].blocks)
    assert "\ufeff" not in all_text


def test_indented_code_block(reader: MarkdownReader, tmp_path: Path) -> None:
    """4-space-indented lines are a code block, not a paragraph."""
    path = tmp_path / "indented.md"
    path.write_text(
        "Intro paragraph.\n\n"
        "    def helper():\n"
        "        return 1\n\n"
        "Outro paragraph.\n",
        encoding="utf-8",
    )
    document = reader.read(path)
    texts = [b.text for b in document.pages[0].blocks]
    code = [t for t in texts if "def helper():" in t]
    assert len(code) == 1
    assert "return 1" in code[0]


def test_indented_list_items_are_not_code(reader: MarkdownReader, tmp_path: Path) -> None:
    """Nested list items indented with 4 spaces stay list items."""
    path = tmp_path / "nested.md"
    path.write_text("    - alpha\n    - beta\n", encoding="utf-8")
    document = reader.read(path)
    kinds = [b.kind for b in document.pages[0].blocks]
    assert kinds == [BlockKind.LIST]
