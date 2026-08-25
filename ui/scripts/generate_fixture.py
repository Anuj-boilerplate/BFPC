"""Dev tool: generate ui/src/mocks/fixtures/fixture.json from report.pdf.

Runs the real BFPC pipeline (parser -> block chunker) over the sample PDF so
the MSW mock serves realistic pages/chunks/kinds and hits whose bboxes point
at real text regions. Requires the repo venv (pymupdf only; no embeddings).

Usage (repo root, venv active):
    python ui/scripts/generate_fixture.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from bfpc.index.chunkers.block import chunk_block  # noqa: E402
from bfpc.parser.pdf_reader import PdfReader  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PDF_PATH = ROOT / "tests" / "fixtures" / "report.pdf"
OUT = ROOT / "ui" / "src" / "mocks" / "fixtures" / "fixture.json"

KINDS = ("text", "table", "heading", "list")
MAX_TEXT = 160


def main() -> None:
    if not PDF_PATH.is_file():
        sys.exit(f"missing sample PDF: {PDF_PATH}")

    document = PdfReader().read(PDF_PATH)
    chunks = chunk_block(document)

    kinds = {kind: 0 for kind in KINDS}
    for chunk in chunks:
        kinds[chunk.kind if chunk.kind in kinds else "text"] += 1

    def text(chunk) -> str:
        return " ".join(chunk.text.split())[:MAX_TEXT]

    # Prefer chunks mentioning "latency" (matches the docs/api.md example),
    # one per page, then fill with any chunks (also one per page).
    per_page: dict[int, object] = {}
    for chunk in chunks:
        if "latency" in chunk.text.lower() and chunk.page not in per_page:
            per_page[chunk.page] = chunk
    for chunk in chunks:
        if chunk.page not in per_page:
            per_page[chunk.page] = chunk
        if len(per_page) >= 5:
            break

    hits = [
        {
            "chunk_id": chunk.id,
            "text": text(chunk),
            "page": chunk.page,
            "kind": chunk.kind if chunk.kind in kinds else "text",
            "score": 0.9 - index * 0.02,
            "bbox": list(chunk.bbox) if chunk.bbox else None,
        }
        for index, chunk in enumerate(list(per_page.values())[:5])
    ]

    fixture = {
        "index": {
            "filename": PDF_PATH.name,
            "source": "pdf",
            "pages": document.page_count,
            "chunks": len(chunks),
            "kinds": kinds,
        },
        "hits": hits,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    print(json.dumps(fixture["index"]))
    for hit in hits:
        print(f"  p{hit['page']} [{hit['kind']:7s}] chunk_id={hit['chunk_id']} {hit['text'][:60]!r}")


if __name__ == "__main__":
    main()
