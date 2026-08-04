# E2E Validation Report — Real Backend, Real Documents

## Objective

Prove, end-to-end through the UI, that the PDF Q&A app works against the **real
backend** (FastAPI + nomic-embed-text-v1.5 + in-repo chunker, block strategy per
`experiments/comparison.md`):

1. Uploading a **different PDF** changes the retrieved evidence (bug #1).
2. Highlights correspond **exactly** to the top-ranked hit's bounding box (bug #2).
3. Non-PDF uploads are rejected; viewer paints and zooms; evidence correspondence
   holds under zoom.

Method: Playwright suite (`ui/e2e/`, 10 tests) run against servers started by
`ui/e2e/run.ps1`, with the acceptance loop `run → diagnose → fix → retest` until
**2 consecutive green runs** (0 failures) or 6 fix cycles.

## Result: 2 consecutive green runs

| Run | Result | Notes |
|-----|--------|-------|
| 1 | **7 passed, 0 failed**, 3 skipped, DONE_EXIT=0 (45.8s) | report.pdf active |
| 2 | **7 passed, 0 failed**, 3 skipped, DONE_EXIT=0 (47.7s) | identical conditions |

(3 skips: `00-fresh-server.spec.ts` is conditional — it only runs against a fresh
server start, skipped when servers are reused.)

## What was actually wrong (the two reported bugs)

Both bugs were **mock artifacts**, not backend bugs:

- `ui/src/main.tsx` started MSW by default in dev. The mock **always served
  hardcoded `report.pdf` bytes and fixed "latency" hits** regardless of which
  file was uploaded or what was asked — hence "same report no matter the PDF"
  and "highlights unrelated to the query".
- Fixes: mock is now opt-in (`VITE_API_MOCK=1`; plain `npm run dev` hits the real
  backend at `127.0.0.1:8000`); `documentUrl()` appends a `?doc=<timestamp>`
  cache-buster and `ViewerScreen` tracks a `docNonce`; backend `GET /api/document`
  sends `Cache-Control: no-store` (`src/bfpc/api/app.py`).

## Bug found in my own test harness (fixed, not the product)

The query-relevance assertion initially measured overlap in the wrong direction:
`tokenOverlap(hit.text, query)` — fraction of the *hit's* jargon-dense tokens
found in a short query — returned 0.06–0.16 for perfectly relevant hits. Corrected
to `tokenOverlap(query, hit.text)` (fraction of the query's significant tokens
found in the hit) with morphology-tolerant matching (`quantization` ≈ `quantizes`,
`nodes` ≈ `node`). Scores for the grounded battery: **0.75 / 0.50 / 1.00**, all
above the 0.25 threshold.

Also: battery queries must be **document-grounded**. "how is CPU memory used
during inference" scores 0.50 (page 20, ONNX-FP16 model card) only because the
report is a benchmark/quantization document; queries about concepts the document
does not cover ("deployment architecture of the server" → 0.00) cannot be
relevance-asserted and were not used.

## Evidence correspondence (bug #2 proof)

For every battery query, the test asserts the highlight geometry (`highlightInfo`)
matches the API's top hit page, then decodes the live PDF (pdf.js `getTextContent`
→ `viewport.convertToViewportPoint` — PDF y-up → page y-down), joins the text
under the highlight bbox, and requires `tokenOverlap(hit.text, under) ≥ 0.8`.
This passed for text chunks and **table rows** (page 12 INT8/FP16 benchmark rows),
i.e. the UI paints exactly the region the backend ranked first — with tight
block-level bboxes, consistent with the block-chunking winner of
`experiments/comparison.md`.

## Cross-document isolation (bug #1 proof)

`02-document-swap.spec.ts` re-uploads a different PDF (cookbook → deploy) and
asserts the search response and highlight page change accordingly; `notes.md` is
rejected with the exact UI toast ("Only PDF files are supported in the UI.").
All queries answered against the *uploaded* document's content only.

## Zoom smoothwork (observed, not asserted)

Zooming during an active highlight kept the highlight anchored to the same page
and scaled the bbox proportionally (asserted with `toBeCloseTo`); canvases
re-render asynchronously, so the suite polls until the highlight settles before
comparing geometry.

## Reproduce

```powershell
powershell -File ui/e2e/run.ps1          # warm backend + run suite (idempotent)
powershell -File ui/e2e/run.ps1 -NoRewarm -Cleanup
```

First index of report.pdf on this CPU ≈ 3.5–6 min (97 chunks, CPU embedding);
the suite is designed so tests skip re-upload when the active document already
matches (`ensureIndexed`).

## Fixture / future work

- report.pdf has no "memory" content; a richer corpus (2+ PDFs per topic) would
  let relevance assertions cover more of the doc.
- The 3 fresh-server tests are skipped on reused servers; CI should run them
  against a cold boot to cover the full path.

*Data: ui/e2e/e2e-green1.log, e2e-green2.log (Playwright line reporter). No data fabricated.*
