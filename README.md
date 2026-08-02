# BFPC

Blazing Fast PDF Companion - document parsing layer.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Usage

```powershell
bfpc report.pdf
bfpc report.pdf --format text
```

## Structure

```
src/bfpc/parser/
├── models.py          # Source, BlockKind, Block, Page, Document
├── base.py            # DocumentReader protocol
├── pdf_reader.py      # PyMuPDF-backed PDF reader
├── markdown_reader.py # Markdown reader
├── docx_reader.py     # DocX reader
└── cli.py             # CLI entry point
```

## Tests

```powershell
pytest
```
