# BFPC HTTP API Contract v1

This document is the **single source of truth** for the BFPC local web API.
The backend must implement exactly what is specified here; any frontend
consuming the API must rely only on what is specified here. Where this
document is silent, nothing is guaranteed.

- Base URL (dev): `http://127.0.0.1:8000`
- JSON bodies: UTF-8, `Content-Type: application/json` on requests.
- All responses are JSON (`application/json`) **except** `GET /api/document`.
- Field order in JSON objects is unspecified; consumers must not rely on it.
- Unknown fields sent in requests are rejected with `422`.

---

## 1. Endpoint summary

| Method | Path             | Purpose                                    |
|--------|------------------|--------------------------------------------|
| POST   | `/api/index`     | Upload + parse + chunk + embed + index a document |
| GET    | `/api/status`    | Query the currently indexed document       |
| POST   | `/api/search`    | Vector search over the active document     |
| GET    | `/api/document`  | Download the raw bytes of the active document |

---

## 2. Common rules

### 2.1 Single active document

The server holds **at most one active document** at a time.

- A successful `POST /api/index` **atomically replaces** the previous
  active document. There is never a moment where the previous document is
  partially visible.
- A **failed** `POST /api/index` (any non-200 response) leaves the previous
  active document **unchanged**. The server builds the new index in a fresh
  state and only swaps it in on success.
- `GET /api/search` and `GET /api/document` operate on the active document.
  If no document has ever been indexed successfully (or the server restarted
  after a clean start), the server state is "no active document".

### 2.2 Error responses

Every non-2xx response is a JSON object with exactly one key:

```json
{ "detail": "<human readable message>" }
```

Status codes used (nothing else is ever returned):

| Code | Meaning |
|------|---------|
| 200  | Success |
| 400  | Request is semantically invalid (e.g. unsupported file extension) |
| 409  | No active document indexed yet |
| 422  | Request body fails schema validation (missing/invalid fields, bad JSON) |
| 500  | Internal error (parse/embed/index failure); previous active doc untouched |

---

## 3. `POST /api/index`

Parse the uploaded file, chunk it with the block chunker, embed all chunks,
and make it the active document.

### 3.1 Request

- `Content-Type: multipart/form-data`
- Exactly one file part, field name **`file`**. The part must include a
  filename; its extension determines how the file is parsed.
- File size is capped at **100 MB**; larger uploads are rejected with 422.
- Supported extensions (case-insensitive) and their `source` values:

| Extension          | `source`   |
|--------------------|------------|
| `.pdf`             | `pdf`      |
| `.md`, `.markdown` | `markdown` |
| `.docx`            | `docx`     |

### 3.2 Response — 200

```json
{
  "filename": "report.pdf",
  "source": "pdf",
  "pages": 20,
  "chunks": 97,
  "kinds": { "text": 63, "table": 18, "heading": 14, "list": 2 }
}
```

Field contract:

| Field      | Type   | Always present | Notes |
|------------|--------|----------------|-------|
| `filename` | string | yes            | Original upload filename, unchanged |
| `source`   | string | yes            | One of `"pdf"`, `"markdown"`, `"docx"` |
| `pages`    | int    | yes            | Number of pages parsed (`>= 1`); markdown/docx report 1 |
| `chunks`   | int    | yes            | Total chunk count (`>= 1`) |
| `kinds`    | object | yes            | Exactly the four keys `text`, `table`, `heading`, `list`; every key is present even when its value is 0; values are non-negative ints summing to `chunks`. The key `image` never appears (image blocks are never chunked) |

### 3.3 Errors

| Condition                          | Code | `detail` contains |
|------------------------------------|------|-------------------|
| `file` part missing / empty / no filename | 422 | — |
| File exceeds the 100 MB upload limit | 422 | — |
| Unsupported extension              | 400  | `Unsupported file type` |
| Document yields zero chunks (blank/empty input) | 400 | — |
| Parse/embed/index failure          | 500  | — |

> A successful `POST /api/index` is *only* possible when the document
> produces at least one chunk. A blank PDF, Markdown, or DocX therefore
> returns 400 and never replaces the active document.

---

## 4. `GET /api/status`

Always returns `200`. Never fails.

### 4.1 Response — 200 (indexed)

```json
{
  "indexed": true,
  "filename": "report.pdf",
  "source": "pdf",
  "pages": 20,
  "chunks": 97
}
```

### 4.2 Response — 200 (nothing indexed)

```json
{
  "indexed": false,
  "filename": null,
  "source": null,
  "pages": null,
  "chunks": null
}
```

Field contract:

| Field      | Type                 | Notes |
|------------|----------------------|-------|
| `indexed`  | boolean              | `true` iff an active document exists |
| `filename` | string \| null       | Null iff `indexed` is false |
| `source`   | string \| null       | As defined in §3.2; null iff not indexed |
| `pages`    | int \| null          | Null iff not indexed |
| `chunks`   | int \| null          | Null iff not indexed |

---

## 5. `POST /api/search`

Vector search over the active document.

### 5.1 Request body

```json
{
  "query": "What is the latency of the INT8 static quantized ONNX model?",
  "top_k": 5
}
```

Field contract:

| Field    | Type    | Required | Default | Constraints |
|----------|---------|----------|---------|-------------|
| `query`  | string  | yes      | —       | Non-empty after trimming; whitespace-only is invalid (422) |
| `top_k`  | int     | no       | `5`     | `1 <= top_k <= 20` (outside range is 422) |

Unknown fields → 422.

### 5.2 Response — 200

```json
{
  "query": "What is the latency of the INT8 static quantized ONNX model?",
  "top_k": 5,
  "hits": [
    {
      "id": "12-2",
      "text": "2 INT8 (Static Quantization + ORT) Multi-core CPU Server Nodes ...",
      "page": 12,
      "kind": "table",
      "score": 0.7305,
      "bbox": [45.0, 520.0, 400.0, 545.0]
    }
  ]
}
```

Field contract:

| Field   | Type               | Notes |
|---------|--------------------|-------|
| `query` | string             | Echo of the trimmed request `query` |
| `top_k` | int                | Echo of the effective `top_k` (requested value, clamped to chunk count only if it exceeds it — see below) |
| `hits`  | array of hit      | Ordered best-first; may be empty |

**Hit object:**

| Field  | Type                 | Always present | Notes |
|--------|----------------------|----------------|-------|
| `id`   | string               | yes            | Opaque unique chunk id; must not be parsed by consumers |
| `text` | string               | yes            | The chunk's full text |
| `page` | int                  | yes            | **1-based** page number (`>= 1`); pdf.js page index = `page - 1` |
| `kind` | string               | yes            | One of `"text"`, `"table"`, `"heading"`, `"list"` |
| `score`| float                | yes            | Cosine similarity of the normalized embeddings; higher is better |
| `bbox` | `[x0, y0, x1, y1]` \| null | yes            | PDF-page region of the chunk, **in PDF points** (see §5.4); `null` for non-PDF sources |

### 5.3 Ordering guarantee

`hits` is sorted by descending `score`. When two hits have scores within
`1e-6` of each other (a "tie"), `text` and `table` rank before `heading`
and `list`; hits with the same score *and* same kind keep FAISS's
insertion order.

### 5.4 Bounding box coordinate system

- Coordinates are PDF **points** (1 pt = 1/72 inch), the native unit of a
  PDF page and of pdf.js at `viewport.scale == 1`.
- Origin is the **top-left corner** of the page.
- **+x is rightward, +y is downward** (y increases toward the page bottom).
- `x0 <= x1` and `y0 <= y1` always.
- To highlight on screen: transform with the same scale factor used to
  render the page (e.g. `viewport.transform` from pdf.js) and draw a
  rectangle covering `[x0, y0]` to `[x1, y1]`.
- The bbox covers the union of the block region(s) that produced the chunk.
- `bbox` is `null` iff the document's `source` is not `"pdf"`.

### 5.5 `top_k` clamping

`hits.length` equals `min(top_k, chunks)` where `chunks` is the active
document's chunk count. `top_k` in the response echoes the *requested*
value, not the clamped one.

### 5.6 Errors

| Condition            | Code | `detail` contains |
|----------------------|------|-------------------|
| No active document   | 409  | —                 |
| Blank `query`        | 422  | —                 |
| `top_k` out of range | 422  | —                 |
| Malformed JSON       | 422  | —                 |
| Internal failure     | 500  | —                 |

---

## 6. `GET /api/document`

Download the raw bytes of the active document.

### 6.1 Response — 200

- Body: the exact bytes of the uploaded file, unchanged.
- `Content-Type` by source:

| `source`  | `Content-Type` |
|-----------|----------------|
| `pdf`     | `application/pdf` |
| `markdown`| `text/markdown` |
| `docx`    | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` |

- `Content-Disposition: inline; filename="<uploaded filename>"`.

### 6.2 Errors

| Condition          | Code |
|--------------------|------|
| No active document | 409  |

---

## 7. Operational contract (backend)

- Chunker used: the registered `"block"` strategy.
- Embedding model: nomic-embed-text-v1.5 with the documented
  `search_query:` / `search_document:` instruction prefixes; embeddings are
  L2-normalized; index is exact cosine (FAISS `IndexFlatIP`).
- Model loading is lazy and cached for the server's lifetime; the first
  `POST /api/index` may take significantly longer than subsequent ones.
- Server runs on `127.0.0.1:8000`; CORS allows origin
  `http://localhost:5173` (and `http://127.0.0.1:5173`).
- The endpoint set is exactly the four listed in §1. No other endpoints are
  part of this contract.
- Requests are handled serially (single active document); concurrent
  requests are not part of the contract.

---

## 8. Conformance checklist (must all hold)

1. `GET /api/status` always returns 200 with the exact shapes of §4.
2. Searching before any successful index returns 409.
3. A failed index leaves status/search/document unchanged.
4. A successful index returns the exact shape of §3.2 and makes
   `GET /api/document` return the uploaded bytes.
5. `hits` ordering follows §5.3.
6. `bbox` follows the top-left origin PDF-point convention of §5.4 and is
   null for non-PDF sources.
7. `page` is 1-based everywhere in responses.
8. Every error is exactly `{"detail": "..."}` with a code from §2.2.
9. `kinds` in §3.2 always contains exactly `text`, `table`, `heading`,
   `list`, never `image`.
10. `top_k` outside `1..20` and blank `query` are rejected with 422.
