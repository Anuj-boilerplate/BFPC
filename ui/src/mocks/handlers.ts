/**
 * MSW mock implementing the BFPC API contract (docs/api.md) for development
 * and tests. Behaviour mirrors the contract: single active document with
 * atomic replace, 409 before any index, 422 on invalid search bodies,
 * `{"detail": "..."}` error shape, and the exact response shapes of §3-§6.
 */

import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../api/config'
import type { Hit, IndexResponse, Kind, Source, StatusIndexed } from '../api/types'
import fixture from './fixtures/fixture.json'

interface FixtureFile {
  index: IndexResponse
  hits: Hit[]
}

const data = fixture as unknown as FixtureFile

export interface MockState {
  indexed: boolean
  filename: string | null
  source: Source | null
  pages: number | null
  chunks: number | null
  kinds: Record<Kind, number>
  hits: Hit[]
}

export function createMockState(): MockState {
  return {
    indexed: false,
    filename: null,
    source: null,
    pages: null,
    chunks: null,
    kinds: { text: 0, table: 0, heading: 0, list: 0 },
    hits: data.hits,
  }
}

export function resetMockState(state: MockState): void {
  const fresh = createMockState()
  Object.assign(state, fresh)
}

function sourceFor(filename: string): Source {
  const lower = filename.toLowerCase()
  if (lower.endsWith('.pdf')) return 'pdf'
  if (lower.endsWith('.docx')) return 'docx'
  return 'markdown'
}

/**
 * Extract the uploaded filename from a raw multipart body. We deliberately
 * avoid `request.formData()`: jsdom's Request implementation (used in the
 * Vitest test environment) never settles on it, while this parser works in
 * browsers and Node alike. Only the filename is needed by the mock.
 */
function filePartFilename(body: string, contentType: string | null): string | null {
  const match = /boundary=(?:"([^"]+)"|([^;]+))/i.exec(contentType ?? '')
  const boundary = match?.[1] ?? match?.[2]
  if (!boundary) return null

  for (const part of body.split(`--${boundary}`)) {
    const headerEnd = part.indexOf('\r\n\r\n')
    if (headerEnd === -1) continue
    const headers = part.slice(0, headerEnd)
    if (/name="([^"]*)"/i.exec(headers)?.[1] !== 'file') continue
    const filename = /filename="([^"]*)"/i.exec(headers)?.[1]
    if (filename) return filename
  }
  return null
}

/** Build the four contract endpoints. `getDocumentBody` supplies bytes for GET /api/document. */
export function createHandlers(
  state: MockState,
  getDocumentBody: () => Promise<BodyInit | null>,
) {
  const base = API_BASE_URL

  return [
    // GET /api/status (§4) — always 200.
    http.get(`${base}/api/status`, () => {
      if (!state.indexed) {
        return HttpResponse.json(
          { indexed: false, filename: null, source: null, pages: null, chunks: null },
        )
      }
      return HttpResponse.json({
        indexed: true,
        filename: state.filename!,
        source: state.source!,
        pages: state.pages!,
        chunks: state.chunks!,
      } satisfies StatusIndexed)
    }),

    // POST /api/index (§3).
    http.post(`${base}/api/index`, async ({ request }) => {
      const filename = filePartFilename(
        await request.text(),
        request.headers.get('content-type'),
      )
      if (!filename) {
        return HttpResponse.json({ detail: 'File part "file" is missing or has no filename' }, { status: 422 })
      }

      const extension = filename.split('.').pop()?.toLowerCase() ?? ''
      if (!['pdf', 'md', 'markdown', 'docx'].includes(extension)) {
        return HttpResponse.json(
          { detail: `Unsupported file type '.${extension}'. Supported: .docx, .markdown, .md, .pdf` },
          { status: 400 },
        )
      }

      state.indexed = true
      state.filename = filename
      state.source = sourceFor(filename)
      state.pages = data.index.pages
      state.chunks = data.index.chunks
      state.kinds = { ...data.index.kinds }

      return HttpResponse.json({
        filename,
        source: state.source,
        pages: state.pages,
        chunks: state.chunks,
        kinds: state.kinds,
      } satisfies IndexResponse)
    }),

    // POST /api/search (§5).
    http.post(`${base}/api/search`, async ({ request }) => {
      if (!state.indexed) {
        return HttpResponse.json({ detail: 'No active document indexed yet' }, { status: 409 })
      }

      let body: Record<string, unknown>
      try {
        body = (await request.json()) as Record<string, unknown>
      } catch {
        return HttpResponse.json({ detail: 'Request body is not valid JSON' }, { status: 422 })
      }

      const allowed = ['query', 'top_k']
      const unknown = Object.keys(body).filter((key) => !allowed.includes(key))
      if (unknown.length > 0) {
        return HttpResponse.json({ detail: `Unknown field(s): ${unknown.join(', ')}` }, { status: 422 })
      }

      const query = typeof body.query === 'string' ? body.query.trim() : ''
      if (!query) {
        return HttpResponse.json({ detail: 'Query must be a non-empty string' }, { status: 422 })
      }

      const rawTopK: unknown = body.top_k
      const topK = rawTopK === undefined ? 5 : rawTopK
      if (typeof topK !== 'number' || !Number.isInteger(topK) || topK < 1 || topK > 20) {
        return HttpResponse.json({ detail: 'top_k must be an integer between 1 and 20' }, { status: 422 })
      }

      return HttpResponse.json({ query, top_k: topK, hits: state.hits.slice(0, topK) })
    }),

    // GET /api/document (§6).
    http.get(`${base}/api/document`, async () => {
      if (!state.indexed) {
        return HttpResponse.json({ detail: 'No active document indexed yet' }, { status: 409 })
      }
      const body = await getDocumentBody()
      if (body === null) {
        return HttpResponse.json({ detail: 'Fixture document bytes unavailable' }, { status: 500 })
      }
      return new HttpResponse(body, {
        headers: {
          'Content-Type': 'application/pdf',
          'Content-Disposition': `inline; filename="${state.filename ?? 'document.pdf'}"`,
          'Cache-Control': 'no-store',
        },
      })
    }),
  ]
}