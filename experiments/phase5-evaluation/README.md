# Phase 5 — Manual Evidence-Graph Evaluation

A small harness for **human** inspection of BFPC's evidence graph. It indexes
`tests/fixtures/report.pdf` once, pushes the 8 queries in `eval_queries.json`
through the full `AnswerPipeline` (retrieval → context → generator), and
prints, per query: status, answer, selected nodes with roles, relationships,
and the full retrieval context (page / kind / chunk / score) each `SOURCE_N`
maps back to.

This is deliberately not an automated metric — the point is to eyeball whether
the pipeline builds sensible evidence graphs on a corpus you can read yourself.

## Run

```powershell
# Real run (needs GEMINI_API_KEY set; embeddings + generation both hit Gemini)
.venv\Scripts\python.exe experiments\phase5-evaluation\run_eval.py `
    --provider gemini --model gemini-2.5-flash `
    --out experiments\phase5-evaluation\results-gemini.json

# Offline smoke run (no network, no API key; deterministic mock generator)
.venv\Scripts\python.exe experiments\phase5-evaluation\run_eval.py --provider mock
```

Other flags: `--pdf` overrides the corpus path (default
`tests/fixtures/report.pdf`). With `--provider mock`, indexing uses a
deterministic hashing embedder, so retrieval is lexical and weaker than real
Gemini embeddings — use it to check wiring, not retrieval quality.
Results JSON mirrors stdout and includes each query's stored expectation for
side-by-side comparison.

## What to look for

Per query, compare the printed run against the `expectation.notes` in
`eval_queries.json`:

- **Right passages in, distractors out** — do the cited `SOURCE_N` pages match
  `relevant_pages`? Are works-cited pages 16–20, neighboring table rows with
  similar numbers, and off-topic sections excluded from *supporting* roles?
- **Sensible roles** — headings/definitions tagged `definition`/`context`,
  concrete numbers and rows as `supporting`, wrap-up claims as `conclusion`;
  no role noise where everything is `context`.
- **Relationships that mean something** — endpoints exist in the context,
  edge types fit semantics (`explains` for mechanism→outcome, `contrasts`
  between competing table rows, `follows_from` along a pipeline chain), and
  multi-passage questions form a coherent chain rather than isolated pairs.
- **Answer coherence and honesty** — figures in the answer match the cited
  passage exactly (18.48 ms vs 15.20 ms confusion is the classic slip), and
  the two gap-probe queries (`eval-07`, `eval-08`) decline or lean
  INSUFFICIENT instead of hallucinating pricing or Kubernetes guidance.
