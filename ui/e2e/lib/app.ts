import { expect, type Page, type Request, type Response } from '@playwright/test'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import type { AnswerResponse, BBox, Hit, SearchResponse } from '../../src/api/types'

export const API_BASE = 'http://127.0.0.1:8000'

export const CORPUS = {
  report: 'report.pdf',
  cookbook: 'cookbook.pdf',
  deploy: 'deploy.pdf',
} as const

export type CorpusName = (typeof CORPUS)[keyof typeof CORPUS]

export function fixturePath(name: string): string {
  return fileURLToPath(new URL(`../fixtures/${name}`, import.meta.url))
}

/** True if the active document on the server is `name`. */
export async function serverHas(page: Page, name: string): Promise<boolean> {
  const res = await page.request.get(`${API_BASE}/api/status`)
  expect(res.status()).toBe(200)
  const body = (await res.json()) as { indexed: boolean; filename: string | null }
  return body.indexed && body.filename === name
}

/**
 * Upload `name` via the real UI (dropzone file input). Handles both start
 * states: fresh server (upload screen) and already-indexed (viewer with a
 * "New document" reset button).
 */
export async function uploadPdf(page: Page, name: string): Promise<void> {
  await page.goto('/')
  await page.waitForSelector('.viewer, .dropzone', { timeout: 30_000 })
  if ((await page.locator('.viewer').count()) > 0) {
    await page.getByRole('button', { name: 'New document' }).click()
    await page.locator('.dropzone').waitFor()
  }
  await page.locator('.dropzone input[type=file]').setInputFiles(fixturePath(name))
  await page.locator('.viewer').waitFor({ timeout: 540_000 })
  await expect(page.locator('.viewer__filename')).toHaveText(name, { timeout: 30_000 })
}

/** Upload `name` only if the server doesn't already have it active. */
export async function ensureIndexed(page: Page, name: string): Promise<void> {
  if (await serverHas(page, name)) {
    await page.goto('/')
    await page.locator('.viewer').waitFor({ timeout: 30_000 })
    return
  }
  await uploadPdf(page, name)
}

/** Ask a question through the UI; returns the parsed /api/search response.
 *  After Phase 12 the UI calls /api/answer; this helper waits for either endpoint
 *  and synthesizes a SearchResponse from an AnswerResponse when needed so
 *  existing e2e assertions keep passing.
 */
export async function ask(page: Page, query: string): Promise<SearchResponse> {
  const [res] = await Promise.all([
    page.waitForResponse(
      (r: Response) =>
        (r.url().includes('/api/search') || r.url().includes('/api/answer')) &&
        r.request().method() === 'POST',
    ),
    (async () => {
      await page.getByLabel('Question').fill(query)
      await page.getByRole('button', { name: 'Ask' }).click()
    })(),
  ])
  expect(res.status()).toBe(200)
  const body = (await res.json()) as unknown
  // If it's an AnswerResponse (has `answer` and `trail`), synthesize hits
  if (body && typeof body === 'object' && 'trail' in body && Array.isArray((body as { trail: unknown }).trail)) {
    const ans = body as { query: string; trail: Array<{ source_id: string; explanation: string; page: number; rects: BBox[] }> }
    const hits = ans.trail.map((t, idx) => ({
      chunk_id: `${idx}-${t.source_id}`,
      text: t.explanation,
      page: t.page,
      kind: 'text' as const,
      score: 1 - idx * 0.1,
      bbox: t.rects[0] ?? null,
      snippet: t.explanation,
      rects: t.rects.length > 0 ? t.rects : null,
    }))
    return { query: ans.query, top_k: hits.length, hits } as SearchResponse
  }
  return body as SearchResponse
}

/** Ask via the new answer endpoint and return the raw AnswerResponse. */
export async function askAnswer(page: Page, query: string): Promise<AnswerResponse> {
  const [res] = await Promise.all([
    page.waitForResponse((r: Response) => r.url().includes('/api/answer') && r.request().method() === 'POST'),
    (async () => {
      await page.getByLabel('Question').fill(query)
      await page.getByRole('button', { name: 'Ask' }).click()
    })(),
  ])
  expect(res.status()).toBe(200)
  return (await res.json()) as import('../../src/api/types').AnswerResponse
}

export interface HighlightInfo {
  pageNumber: number
  left: number
  top: number
  width: number
  height: number
}

/** Read the best (rank-0) highlight rect and the page it sits on. */
export async function highlightInfo(page: Page): Promise<HighlightInfo> {
  const highlight = page.locator('.pdf-page .highlight').first()
  await expect(highlight).toBeVisible({ timeout: 30_000 })
  const host = highlight.locator('xpath=ancestor::div[contains(@class,"pdf-page")][1]')
  const box = (await highlight.boundingBox()) ?? { x: 0, y: 0, width: 0, height: 0 }
  const pageNumber = Number(await host.getAttribute('data-page-number'))
  expect(pageNumber).toBeGreaterThanOrEqual(1)
  return { pageNumber, left: box.x, top: box.y, width: box.width, height: box.height }
}

export { expect }
export type { Hit, Request }
