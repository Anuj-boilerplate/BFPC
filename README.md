---
title: BFPC
emoji: 📄
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 8000
pinned: false
---

# BFPC

Blazing Fast PDF Companion - parse documents into blocks, chunk them, embed
them, and answer natural-language questions with the answer highlighted
directly on the PDF.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
cd ui
npm install
cd ..
```

## Usage

### CLI

```powershell
bfpc parse tests/fixtures/report.pdf
bfpc parse tests/fixtures/report.pdf --format text
```

### HTTP API

```powershell
$env:GEMINI_API_KEY = "..."   # embedding API key (or set it as a system env var)
bfpc serve        # uvicorn on http://127.0.0.1:8000
```

The API contract lives in `docs/api.md` (single source of truth). Endpoints:

- `POST /api/index`    upload + parse + chunk + embed + index
- `GET  /api/status`   current active document summary
- `POST /api/search`   vector search over the active document
- `GET  /api/document` raw bytes of the active document

### Web UI

```powershell
cd ui
npm run dev       # Vite dev server on http://localhost:5173
```

## Structure

```
src/bfpc/
├── parser/       # PDF (PyMuPDF), Markdown, DocX readers + CLI
├── index/        # chunking strategies, embedding, FAISS vector index
└── api/          # FastAPI server implementing docs/api.md
tests/            # pytest suite (contract conformance, readers, chunker, index)
ui/               # Vite + React + pdf.js frontend
docs/api.md       # HTTP API contract
```

## Tests

```powershell
pytest                 # backend
cd ui; npm test        # frontend unit tests
cd ui; npm run test:e2e  # Playwright end-to-end (see ui/e2e/run.ps1)
```
