/**
 * Types mirroring the BFPC HTTP API contract (docs/api.md) exactly.
 * The backend implements the contract; the frontend must rely only on what
 * is specified there. When docs/api.md is silent, nothing is guaranteed.
 */

export type Source = 'pdf' | 'markdown' | 'docx'

export type Kind = 'text' | 'table' | 'heading' | 'list'

/** PDF-page bounding box in PDF points, top-left origin, +y downward (§5.4). */
export type BBox = [number, number, number, number]

/** POST /api/index -> 200 (§3.2). */
export interface IndexResponse {
  filename: string
  source: Source
  pages: number
  chunks: number
  kinds: Record<Kind, number>
}

/** GET /api/status -> 200, indexed (§4.1). */
export interface StatusIndexed {
  indexed: true
  filename: string
  source: Source
  pages: number
  chunks: number
}

/** GET /api/status -> 200, nothing indexed (§4.2). */
export interface StatusEmpty {
  indexed: false
  filename: null
  source: null
  pages: null
  chunks: null
}

export type StatusResponse = StatusIndexed | StatusEmpty

/** One retrieval result (§5.2). */
export interface Hit {
  id: string
  text: string
  page: number
  kind: Kind
  score: number
  bbox: BBox | null
  snippet: string | null // NEW: best-matching sentence from the chunk
  rects: BBox[] | null // NEW: tight rectangles for the snippet
}

/** POST /api/search -> 200 (§5.2). */
export interface SearchResponse {
  query: string
  top_k: number
  hits: Hit[]
}