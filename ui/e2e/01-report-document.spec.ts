/**
 * The real report: document identity, search relevance, evidence-correspondent
 * highlighting, zoom, and reload persistence — all against report.pdf, which
 * run.ps1 pre-indexes so this file runs on a warm backend.
 */
import { test, expect } from '@playwright/test'
import { API_BASE, CORPUS, ask, ensureIndexed, highlightInfo } from './lib/app'
import { extractText, textUnder, tokenOverlap, type BBox } from './lib/pdf'

test.describe('report.pdf end-to-end', () => {
  test('renders the correct document with all 20 pages painted', async ({ page }) => {
    await ensureIndexed(page, CORPUS.report)
    await expect(page.locator('.viewer__filename')).toHaveText(CORPUS.report)
    await expect(page.locator('.viewer__meta')).toContainText('20 pages', { timeout: 60_000 })

    await expect(page.locator('.pdf-page')).toHaveCount(20, { timeout: 120_000 })

    const painted = await page.locator('.pdf-page__canvas').first().evaluate((canvas) => {
      const c = canvas as HTMLCanvasElement
      const ctx = c.getContext('2d')
      if (!ctx) return false
      const data = ctx.getImageData(0, 0, c.width, c.height).data
      for (let i = 0; i < data.length; i += 40) {
        if (data[i] !== 255) return true
      }
      return false
    })
    expect(painted).toBe(true)
    await expect(page.locator('.toast')).toHaveCount(0)
  })

  test('retrieves relevant evidence and highlights exactly the reported region', async ({ page }) => {
    await ensureIndexed(page, CORPUS.report)

    const battery = [
      { query: 'What is the latency of the INT8 static quantized ONNX model?', strict: /int8|onnx|latency/i },
      { query: 'how is CPU memory used during inference', strict: null },
      { query: 'what about FP16 and CUDA', strict: null },
    ]

    for (const { query, strict } of battery) {
      const res = await ask(page, query)
      expect(res.hits.length).toBeGreaterThan(0)
      const hit = res.hits[0]

      if (strict) {
        expect(hit.text, `top hit must address "${query}"`).toMatch(strict)
      } else {
        const overlap = tokenOverlap(query, hit.text)
        expect(overlap, `top hit must share significant tokens with "${query}" (${overlap.toFixed(2)})`).toBeGreaterThanOrEqual(0.25)
      }

      // UI-level: the best hit is highlighted on its page (top-3 hits may
      // each add more rects, ranks 1+ are faded in the UI).
      const info = await highlightInfo(page)
      expect(info.pageNumber).toBe(hit.page)
      expect(info.width).toBeGreaterThan(1)
      expect(info.height).toBeGreaterThan(1)

      // Evidence correspondence: the text physically under the chunk bbox
      // must contain most of the tokens of the hit the API ranked first.
      expect(hit.bbox).not.toBeNull()
      const bytes = new Uint8Array(await (await page.request.get(`${API_BASE}/api/document?e2e=1`)).body())
      const pages = await extractText(bytes)
      const target = pages[hit.page - 1]
      expect(target).toBeDefined()
      expect(hit.bbox![0]).toBeGreaterThanOrEqual(0)
      expect(hit.bbox![1]).toBeGreaterThanOrEqual(0)
      expect(hit.bbox![2]).toBeLessThanOrEqual(target.width + 0.5)
      expect(hit.bbox![3]).toBeLessThanOrEqual(target.height + 0.5)

      const under = textUnder(target, hit.bbox as BBox)
      const overlap = tokenOverlap(hit.text, under)
      expect(
        overlap,
        `top hit tokens must appear under the highlight bbox (overlap ${overlap.toFixed(2)})\nhit:  ${hit.text}\nunder: ${under}`,
      ).toBeGreaterThanOrEqual(0.8)

      // Pixel-perfect layer: every tight snippet rect lands inside the page
      // and the union of the snippet's rects covers the snippet's tokens.
      expect(hit.snippet, 'top hit must carry a localized snippet').not.toBeNull()
      expect(hit.rects, 'top hit must carry tight snippet rects').not.toBeNull()
      const rects = hit.rects as BBox[]
      expect(rects.length).toBeGreaterThanOrEqual(1)
      for (const rect of rects) {
        expect(rect[0]).toBeGreaterThanOrEqual(0)
        expect(rect[1]).toBeGreaterThanOrEqual(0)
        expect(rect[2]).toBeLessThanOrEqual(target.width + 0.5)
        expect(rect[3]).toBeLessThanOrEqual(target.height + 0.5)
      }
      const snippetUnder = rects.map((rect) => textUnder(target, rect)).join(' ')
      const snippetOverlap = tokenOverlap(hit.snippet as string, snippetUnder)
      expect(
        snippetOverlap,
        `snippet tokens must appear under the tight rects (overlap ${snippetOverlap.toFixed(2)})\nsnippet: ${hit.snippet}\nunder: ${snippetUnder}`,
      ).toBeGreaterThanOrEqual(0.8)
    }
  })

  test('highlight persists and scales when zooming', async ({ page }) => {
    await ensureIndexed(page, CORPUS.report)
    await ask(page, 'What is the latency of the INT8 static quantized ONNX model?')

    const scaleOf = async () => {
      const text = await page.locator('.pdfviewer__zoom-label').textContent()
      return Number.parseInt(text ?? '100', 10) / 100
    }

    const before = await highlightInfo(page)
    const beforeScale = await scaleOf()
    expect(before.width).toBeGreaterThan(1)

    await page.getByRole('button', { name: 'Zoom in' }).click()
    const afterScale = await scaleOf()
    expect(afterScale / beforeScale).toBeGreaterThan(1.1)
    expect(afterScale / beforeScale).toBeLessThan(1.4)

    // Wait until the highlight fully settles at the new scale (page
    // canvases re-render asynchronously) before comparing geometry.
    const expectedWidth = (before.width * afterScale) / beforeScale
    const expectedHeight = (before.height * afterScale) / beforeScale
    await expect
      .poll(async () => (await highlightInfo(page)).width, { timeout: 60_000 })
      .toBeCloseTo(expectedWidth, -1)
    const after = await highlightInfo(page)
    expect(after.pageNumber).toBe(before.pageNumber)
    expect(after.width).toBeCloseTo(expectedWidth, -1)
    expect(after.height).toBeCloseTo(expectedHeight, -1)
  })

  test('restores the viewer after a reload and keeps search working', async ({ page }) => {
    await ensureIndexed(page, CORPUS.report)

    await page.reload()
    await page.locator('.viewer').waitFor({ timeout: 60_000 })
    await expect(page.locator('.viewer__filename')).toHaveText(CORPUS.report)
    await expect(page.locator('.dropzone')).toHaveCount(0)
    await expect(page.locator('.toast')).toHaveCount(0)

    const res = await ask(page, 'What is the latency of the INT8 static quantized ONNX model?')
    expect(res.hits.length).toBeGreaterThan(0)
    expect(res.hits[0].text).toMatch(/int8|onnx|latency/i)
  })
})
