"""CLI entry point: ``bfpc parse <file>``.

The ``parse`` command reads a Markdown, DocX, or PDF file into the shared
in-memory document model and prints a per-page block summary.
"""

from __future__ import annotations

from pathlib import Path

import typer

from bfpc.parser.docx_reader import DocxReader
from bfpc.parser.markdown_reader import MarkdownReader
from bfpc.parser.models import BlockKind, Document, Source
from bfpc.parser.pdf_reader import PdfReader

app = typer.Typer(add_completion=False)

_READERS = {
    ".pdf": PdfReader(),
    ".md": MarkdownReader(),
    ".markdown": MarkdownReader(),
    ".docx": DocxReader(),
}


def parse_document(path: Path) -> Document:
    """Route ``path`` to the matching reader by extension.

    :param path: path to a supported document.
    :return: the parsed document.
    :raises ValueError: if the extension is unsupported.
    """
    extension = path.suffix.lower()
    reader = _READERS.get(extension)
    if reader is None:
        supported = ", ".join(sorted(_READERS))
        raise ValueError(f"Unsupported file type '{extension}'. Supported: {supported}")
    return reader.read(path)


@app.command()
def parse(
    file: Path = typer.Argument(..., exists=False, help="Path to a PDF, Markdown, or DocX file"),
    format: str = typer.Option("summary", "--format", help="Output mode: 'summary' or 'text'"),
) -> None:
    """Parse a document and print a summary or its flattened text."""
    try:
        document = parse_document(file)
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1)

    if format == "text":
        _print_text(document)
    elif format == "summary":
        _print_summary(document)
    else:
        typer.echo(f"error: unknown format '{format}' (use 'summary' or 'text')", err=True)
        raise typer.Exit(code=2)


def _print_summary(document: Document) -> None:
    typer.echo(f"{document.path} [{document.source.value}, {document.page_count} page(s)]")
    for page in document.pages:
        if not page.blocks:
            typer.echo(f"  page {page.number}: <empty>")
            continue
        for block in page.blocks:
            kind = block.kind
            preview = block.text[:60].replace("\n", " ")
            typer.echo(f"  page {page.number} [{kind.value:8s}] {preview}")


def _print_text(document: Document) -> None:
    for page in document.pages:
        for block in page.blocks:
            if block.kind != BlockKind.IMAGE:
                typer.echo(block.text)
                typer.echo("")


if __name__ == "__main__":
    app()
