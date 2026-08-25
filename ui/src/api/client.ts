import { API_BASE_URL } from './config'
import type { AnswerResponse, IndexResponse, SearchResponse, StatusResponse } from './types'

export type { BBox, Hit, IndexResponse, Kind, SearchResponse, Source, StatusEmpty, StatusIndexed, StatusResponse } from './types'

/** HTTP error carrying the contract's `{ "detail": "..." }` (§2.2). Status 0 = transport failure. */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function detailOr(res: Response): Promise<string> {
  try {
    const body: unknown = await res.json()
    if (body && typeof body === 'object' && typeof (body as { detail?: unknown }).detail === 'string') {
      return (body as { detail: string }).detail
    }
  } catch {
    /* non-JSON body */
  }
  return `Request failed with status ${res.status}.`
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}${path}`, init)
  } catch {
    throw new ApiError(0, `Cannot reach the BFPC server at ${API_BASE_URL}. Is it running?`)
  }
  if (!res.ok) {
    throw new ApiError(res.status, await detailOr(res))
  }
  return (await res.json()) as T
}

/** GET /api/status (§4). Always 200; `indexed` tells whether a document is active. */
export function getStatus(): Promise<StatusResponse> {
  return requestJson('/api/status')
}

/** POST /api/index (§3). Uploads, parses, chunks, embeds, and indexes `file`. */
export function indexDocument(file: File): Promise<IndexResponse> {
  const form = new FormData()
  form.append('file', file)
  return requestJson('/api/index', { method: 'POST', body: form })
}

/** POST /api/search (§5). Finds the top-k chunks for `query`. */
export function search(query: string, topK = 5): Promise<SearchResponse> {
  return requestJson('/api/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query: query.trim(), top_k: topK }),
  })
}

/** POST /api/answer (§8). Full pipeline answer with trail. */
export function askQuestion(query: string): Promise<AnswerResponse> {
  return requestJson('/api/answer', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query: query.trim() }),
  })
}

/**
 * GET /api/document (§6). Absolute URL of the active document bytes (for pdf.js).
 * `nonce` cache-busts the request: the URL is otherwise stable across re-indexes,
 * and stale browser caches can otherwise serve the previous document's bytes.
 */
export function documentUrl(nonce?: string | number): string {
  return `${API_BASE_URL}/api/document?doc=${encodeURIComponent(String(nonce ?? Date.now()))}`
}