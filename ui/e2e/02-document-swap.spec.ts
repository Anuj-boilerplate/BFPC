/**
 * Document swapping and cross-document isolation: uploading a different
 * document must atomically replace the active one — content, rendered
 * canvas, and search results — with no stale bytes or retrieval bleed.
 */
import { test, expect } from '@playwright/test'
import { createHash } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { API_BASE, CORPUS, ask, ensureIndexed, fixturePath, uploadPdf } from './lib/app'

test.describe('document swapping', () => {
  test('re-uploading a different document replaces the active one', async ({ page }) => {
    await uploadPdf(page, CORPUS.cookbook)
    await expect(page.locator('.viewer__meta')).toContainText('3 pages', { timeout: 60_000 })
    await expect(page.locator('.pdf-page')).toHaveCount(3, { timeout: 120_000 })

    // cookbook-specific question finds cookbook content.
    let res = await ask(page, 'how do I create a virtualenv for my project')
    expect(res.hits.length).toBeGreaterThan(0)
    expect(res.hits[0].text.toLowerCase()).toContain('virtualenv')

    // Swap to a topically disjoint document.
    await uploadPdf(page, CORPUS.deploy)
    await expect(page.locator('.viewer__meta')).toContainText('3 pages', { timeout: 60_000 })

    res = await ask(page, 'how do I perform a canary rollout')
    expect(res.hits.length).toBeGreaterThan(0)
    expect(res.hits[0].text.toLowerCase()).toContain('canary')

    // The cookbook must be gone: a cookbook question must NOT retrieve
    // cookbook text from the now-active deployment guide.
    res = await ask(page, 'how do I create a virtualenv')
    for (const hit of res.hits) {
      expect(hit.text.toLowerCase()).not.toContain('virtualenv')
    }
  })

  test('serves the exact uploaded bytes for the active document', async ({ page }) => {
    await ensureIndexed(page, CORPUS.cookbook)

    const res = await page.request.get(`${API_BASE}/api/document?e2e=1`)
    expect(res.status()).toBe(200)
    expect(res.headers()['content-type']).toContain('application/pdf')
    expect(res.headers()['cache-control']).toContain('no-store')

    const served = Buffer.from(await res.body())
    const local = Buffer.from(await readFile(fixturePath(CORPUS.cookbook)))
    expect(createHash('sha256').update(served).digest('hex')).toBe(
      createHash('sha256').update(local).digest('hex'),
    )
  })

  test('rejects non-PDF files even when a document is already active', async ({ page }) => {
    await ensureIndexed(page, CORPUS.cookbook)
    await page.getByRole('button', { name: 'New document' }).click()
    await page.locator('.dropzone').waitFor()
    await page.locator('.dropzone input[type=file]').setInputFiles(fixturePath('notes.md'))
    await expect(page.locator('.toast')).toHaveText('Only PDF files are supported in the UI.')
  })
})
