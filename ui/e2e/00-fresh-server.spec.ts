/**
 * Fresh-server behaviour. These tests only make sense when the backend has
 * NO active document, so they self-skip when the server is already indexed
 * (e.g. warm runs via run.ps1). To exercise them: run against a fresh
 * backend with no warm-up.
 */
import { test, expect } from '@playwright/test'
import { API_BASE, fixturePath } from './lib/app'

let clean = false

test.beforeAll(async ({ request }) => {
  const res = await request.get(`${API_BASE}/api/status`)
  clean = res.status() === 200 && (await res.json()).indexed === false
})

test('shows the upload screen with no errors', async ({ page }) => {
  test.skip(!clean, 'server already indexed; use a fresh backend to exercise this')
  await page.goto('/')
  await page.locator('.dropzone').waitFor({ timeout: 30_000 })
  await expect(page.locator('.toast')).toHaveCount(0)
  await expect(page.getByText('Drop a PDF here, or click to browse')).toBeVisible()
})

test('rejects non-PDF files client-side with a toast', async ({ page }) => {
  test.skip(!clean, 'server already indexed; use a fresh backend to exercise this')
  await page.goto('/')
  await page.locator('.dropzone').waitFor()
  await page.locator('.dropzone input[type=file]').setInputFiles(fixturePath('notes.md'))
  await expect(page.locator('.toast')).toHaveText('Only PDF files are supported in the UI.')
  await expect(page.locator('.viewer')).toHaveCount(0)
})

test('API returns 409 for search and document before any index', async ({ request }) => {
  test.skip(!clean, 'server already indexed; use a fresh backend to exercise this')
  for (const path of ['/api/search', '/api/document']) {
    const res =
      path === '/api/search'
        ? await request.post(`${API_BASE}${path}`, { data: { query: 'anything' } })
        : await request.get(`${API_BASE}${path}`)
    expect(res.status()).toBe(409)
    const body = await res.json()
    expect(body).toMatchObject({ detail: expect.any(String) })
  }
})
