// @vitest-environment node
import { documentUrl, getStatus, indexDocument, search } from '../api/client'

const pdfFile = () => new File(['%PDF-1.4 fake bytes'], 'report.pdf', { type: 'application/pdf' })

describe('api client (contract-driven)', () => {
  it('reports no active document before any index', async () => {
    await expect(getStatus()).resolves.toEqual({
      indexed: false,
      filename: null,
      source: null,
      pages: null,
      chunks: null,
    })
  })

  it('indexes a PDF and makes it the active document', async () => {
    const response = await indexDocument(pdfFile())
    expect(response).toMatchObject({ filename: 'report.pdf', source: 'pdf', pages: 20, chunks: 97 })
    expect(response.kinds).toEqual({ text: 63, table: 18, heading: 14, list: 2 })

    const status = await getStatus()
    expect(status).toMatchObject({ indexed: true, filename: 'report.pdf', source: 'pdf', pages: 20, chunks: 97 })
  })

  it('accepts markdown and docx uploads with the right source', async () => {
    await indexDocument(new File(['# hi'], 'notes.md', { type: 'text/markdown' }))
    await expect(getStatus()).resolves.toMatchObject({ indexed: true, source: 'markdown', filename: 'notes.md' })

    await indexDocument(new File(['x'], 'notes.docx', { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }))
    await expect(getStatus()).resolves.toMatchObject({ indexed: true, source: 'docx', filename: 'notes.docx' })
  })

  it('rejects unsupported extensions with a 400 ApiError', async () => {
    const error = await indexDocument(new File(['x'], 'notes.txt', { type: 'text/plain' })).catch((e: unknown) => e)
    expect(error).toMatchObject({ status: 400 })
    expect((error as { message: string }).message).toContain('Unsupported file type')
  })

  it('returns a 409 ApiError for searches before an index', async () => {
    await expect(search('anything')).rejects.toMatchObject({ status: 409 })
  })

  it('rejects blank queries and out-of-range top_k with 422', async () => {
    await indexDocument(pdfFile())
    await expect(search('   ')).rejects.toMatchObject({ status: 422 })
    await expect(search('ok', 0)).rejects.toMatchObject({ status: 422 })
    await expect(search('ok', 21)).rejects.toMatchObject({ status: 422 })
  })

  it('rejects unknown search fields with 422', async () => {
    await indexDocument(pdfFile())
    const error = await fetch(documentUrl().replace('/api/document', '/api/search'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: 'x', filter: 'y' }),
    }).then((res) => res.json() as Promise<{ detail: string }>)
    expect(error.detail).toContain('Unknown field')
  })

  it('returns ordered hits with 1-based pages, bboxes, kinds and scores', async () => {
    await indexDocument(pdfFile())
    const result = await search('latency', 3)
    expect(result.query).toBe('latency')
    expect(result.top_k).toBe(3)
    expect(result.hits).toHaveLength(3)
    const [first] = result.hits
    expect(first).toMatchObject({ page: 10, kind: 'text' })
    expect(first.bbox).toHaveLength(4)
    expect(first.score).toBeGreaterThanOrEqual(0)
  })

  it('serves the document bytes once indexed (Content-Type application/pdf)', async () => {
    await indexDocument(pdfFile())
    const res = await fetch(documentUrl())
    expect(res.status).toBe(200)
    expect(res.headers.get('content-type')).toContain('application/pdf')
    const bytes = new Uint8Array(await res.arrayBuffer())
    expect(bytes.length).toBeGreaterThan(0)
  })

  it('points documentUrl at the API base with a cache-busting nonce', () => {
    expect(documentUrl('abc')).toBe('http://127.0.0.1:8000/api/document?doc=abc')
    expect(documentUrl()).toMatch(/\/api\/document\?doc=\d+/)
  })
})
