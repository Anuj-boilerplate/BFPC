"""Tests for CLI routing."""

from __future__ import annotations

from pathlib import Path

import pytest

from bfpc.parser.cli import parse_document
from bfpc.parser.models import Source


def test_routes_by_extension(markdown_file: Path) -> None:
    document = parse_document(markdown_file)
    assert document.source == Source.MARKDOWN


def test_unsupported_extension_raises(tmp_path: Path) -> None:
    unsupported = tmp_path / "notes.txt"
    unsupported.write_text("hello", encoding="utf-8")
    with pytest.raises(ValueError):
        parse_document(unsupported)


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        parse_document(tmp_path / "missing.pdf")
