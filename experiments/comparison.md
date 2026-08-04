# BFPC Chunking Experiment — Comparison Report

Single-document sweep: `report.pdf` (20 pages), 5 queries (r1–r5).
All numbers come directly from `experiments/results/*.json`.

## Summary Table

| Strategy | hit@5 | MRR | n_chunks | r5 (p12, INT8 latency) | Verdict |
|----------|-------|-----|----------|------------------------|---------|
| **block** | 1.0 | 1.0 | 144 | rank 1 | Perfect; finest granularity, highest index cost |
| **page** | 1.0 | 0.84 | 20 | rank 5 | Perfect recall; dilution drags MRR; coarse highlights |
| **sentence** | 0.8 | 0.8 | 27 | miss | Loses targeted facts to adjacent similar chunks |
| **recursive** | 0.8 | 0.8 | 30 | miss | Same factoid miss; variable-size windows |
| **hybrid** | 0.8 | 0.8 | 26 | miss | Semantic merges bury the specific fact |
| **semantic** | 0.8 | 0.8 | 55 | miss | Same miss; ~590 s/20 pages chunk-time cost |
| **fixed** | 0.8 | 0.7 | 41 | miss | Worst ranking (r1 hit at rank 2); arbitrary windows |

---

## Failure Analysis: r5 — "What is the latency of the INT8 static quantized ONNX model?" (expected page 12)

Only one query separates the winners from the pack, and it is a **precision-on-a-fact** (factoid) query.

| Strategy | r5 found pages | Rank |
|----------|---------------|------|
| block    | [12, 10, 20, 10, 11] | 1 |
| page     | [11, 10, 20, 2, 12]  | 5 |
| fixed    | [10, 11, 20, 10, 11] | miss |
| sentence | [11, 10, 20, 19, 1]  | miss |
| recursive| [11, 10, 20, 19, 2]  | miss |
| hybrid   | [11, 10, 20, 19, 1]  | miss |
| semantic | [10, 11, 20, 11, 10] | miss |

**Why the fine-grained strategies miss it:** page 12's latency figure sits inside
a quantization section where nearby text (pages 10–11: FP16/FP8/INT8 PTQ
discussion, page 20: performance table) shares the query's vocabulary.
Chunking strategies that *merge* adjacent sentences or blocks (sentence,
recursive, hybrid, semantic) or cut *arbitrary* windows (fixed) dilute the
"INT8 + latency" terms into a larger chunk whose embedding is dominated by the
surrounding topic rather than the specific fact. The result: page 12 is never
retrieved in the top 5.

- **block wins** because each table row / isolated cell is its own tiny chunk —
  the exact `INT8 (Static Quantization + ORT)` row is retrieved at rank 1, verbatim.
- **page survives** only by page anchor: page 12 is in the top 5 (rank 5), but
  the answer is deep-diluted by the rest of the page, so MRR collapses to 0.84.
- **fixed** additionally slips r1 to rank 2 (window boundary cuts the compare-table),
  the only strategy that failed on a retrieval of an already-clear page.

Every other query (r1–r4) was retrieved at rank 1 by every strategy except
fixed's r1 (rank 2). The fixture's other answers live in clean, polished passages;
r5 is the discriminating adversarial query.

---

## Winner: Block Chunking

### Justification

Two strategies hit@5 = 1.0, but only one gets MRR = 1.0 **and** the right highlight shape:

| Dimension | block | page |
|-----------|-------|------|
| hit@5 | 1.0 | 1.0 |
| MRR | 1.0 | 0.84 |
| Chunks (report.pdf) | 144 | 20 |
| Highlight precision | exact parser-block bbox (a table row / heading / bullet) | whole page |
| Failure (r5) | rank 1, verbatim exact answer | rank 5, diluted by its own page |
| Thematic-motif alignment | chunk = document's own structural unit | chunk = a page that often mixes several topics |

For BFPC's *thematic-motif* use case — where a retrieval hit becomes a highlight
region over the document — **block chunking is the only strategy that returns the
answer AND a tight bounding box for it**. A block is typically a paragraph, heading,
list item, or single table row; when the app highlights the chunk's bbox it covers
exactly the motif, not half a page of neighboring noise. Page highlights (the page
strategy) always paint the entire page, burying the theme.

The acknowledged cost of block chunking is index size: 144 chunks for a 20-page
document (~7 avg per page). Embedding 144 short chunks is cheap at chunk-time
(~0 extra), but means more vectors in the store and, at retrieval, more candidate
chunks whose near-duplicate vocabularies can shuffle ranks (the original block
stumble on m3 occurred in the earlier multi-doc run). Round-2 tuning below targets
both the size and the noise.

**Why not page?** Page = perfect recall but 0.84 MRR, and every highlight covers
the full page. For thematic motifs that live in a passage, not a page, that's a
precision miss. Result page-12 shows the dilution mechanism exactly.

**Why not the 0.8/0.8 group?** They concede the ONE query that matters for
factoid retrieval, and they do so systematically (paragraph 6: shared vocabulary
pages crowd out the answer page). Semantic additionally pays an enormous upfront
cost (~590 s for a 20-page document, embedding every sentence twice).

---

## Round-2 Tuning Recommendations

### Block (winner) — reduce chunk count, sharpen embeddings

| No | Change | Rationale |
|----|--------|-----------|
| 1 | Merge consecutive LIST items on the same page (2–4 items, no intervening blank) into one chunk | Kill the many single-line list chunks that carry thin embeddings, cutting 144 → ~80–100 chunks |
| 2 | After block extraction, pass the block's text through the existing-to-sentence cap (2000 chars) BEFORE registering, so one block yields max title to sub-chunks | Keeps the exact-answer property of r5 while reducing duplicate row fragments |
| 3 | Optional: sub-page bbox with a few px padding for visual overlap | Keeps highlight tight but slightly more forgiving on the Parser's bbox rival |
| 4 | Block kind ordering in scores: prefer TEXT/TABLE over LIST and dictation when ties | Improves the "right topic page at rank 1" behavior |

### Page (runner-up) — refine granularity without losing recall

| No | Change | Rationale |
|----|--------|-----------|
| 1 | Split pages at block/heading boundaries into "page sections" (~2–4/age page) | Preserves the page anchor for recall while making the highlight cover a section, not the whole page |
| 2 | Add overlap not applicable; instead dedupe page top-1 by capturing the block=answer | no chunk-size change to prove |

### Semantic / Hybrid (theme axis) — make factoid query safer

| No | Change | Rationale |
|----|--------|-----------|
| 1 | **Table-aware boundary detection**: never merge across a table row or when either side's block kind is TABLE | Prevents r1's scrambled table fragment and keeps table answers isolated (block-style) |
| 2 | Raise merge threshold empirically on a factoid-tunnel (0.45 → ~0.55 for hybrid; 0.7 keep for semantic) | Fine merge → dilution; slightly higher threshold re-isolates the INT8 row |
| 3 | Cap merge-group size to one page (already true) AND to ~3 sentences tail-heavy | Bound the "buried fact" window |
| 4 | Amortize sentence-embedding: cache sentence vectors at parse time / reuse harness index embed | Attacks the ~590 s factor-of-2 embedding cost on 20 pages |

### Fixed — deprioritize

Arbitrary windows cut tables mid-row (r1 rank 2) and lose the INT8 fact. Only keep
if chunk-count-cost is the binding constraint and highlight precision is ignored.

---

### Fixture improvement for Round 3

r1–r4 are traversed trivially (rank 1 everywhere); the whole setup scouts
strategy only on r5. Add 2–3 more :**factoid** and **cross-section** ("see §3.2")
queries, plus a table that spans a page boundary, so page/semantic strengths get
separated from the block's exact-row behavior.

*Report generated from `experiments/results/*.json` and `experiments/results/*.md`. No data fabricated.*