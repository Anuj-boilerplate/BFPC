/**
 * Node-side pdf.js text extraction for evidence-correspondence assertions.
 *
 * We re-parse the exact bytes served by GET /api/document (never the browser
 * canvas) so we can compare the *text actually underneath a highlight bbox*
 * against the hit text the API claims is evidence for that region.
 */

import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'

export interface TextItemBox {
  str: string
  /** baseline origin in PDF points, top-left origin, y-down (§5.4 space). */
  x: number
  y: number
}

export interface PdfPage {
  pageNumber: number
  width: number
  height: number
  items: TextItemBox[]
}

const require = createRequire(import.meta.url)
const WORKER_SRC = pathToFileURL(require.resolve('pdfjs-dist/build/pdf.worker.mjs')).href

export async function extractText(bytes: Uint8Array): Promise<PdfPage[]> {
  const pdfjs = await import('pdfjs-dist/legacy/build/pdf.mjs')
  pdfjs.GlobalWorkerOptions.workerSrc = WORKER_SRC
  const doc = await pdfjs.getDocument({ data: bytes }).promise
  const pages: PdfPage[] = []
  try {
    for (let n = 1; n <= doc.numPages; n++) {
      const page = await doc.getPage(n)
      const viewport = page.getViewport({ scale: 1 })
      const content = await page.getTextContent()
      pages.push({
        pageNumber: n,
        width: viewport.width,
        height: viewport.height,
        // getTextContent() yields items in PDF native space (bottom-left
        // origin, y up); the viewport maps them to the top-left, y-down
        // space that §5.4 bboxes use.
        items: content.items
          .map((item) => {
            const t = (item as { transform?: number[] }).transform ?? [1, 0, 0, 1, 0, 0]
            const str = typeof (item as { str?: unknown }).str === 'string' ? (item as { str: string }).str : ''
            const [x, y] = viewport.convertToViewportPoint(t[4], t[5])
            return { str, x, y }
          })
          .filter((item) => item.str.trim().length > 0),
      })
    }
  } finally {
    await doc.destroy()
  }
  return pages
}

export type BBox = [number, number, number, number]

/**
 * Concatenate the text of every item whose baseline (x, y) lies inside the
 * (expanded) bounding box. The chunk bbox is the block's text box, so the
 * baselines of every matching line fall inside; the pad absorbs baseline vs
 * glyph-top slack.
 */
export function textUnder(pdfPage: PdfPage, bbox: BBox, pad = 2): string {
  const [x0, y0, x1, y1] = bbox
  return pdfPage.items
    .filter((item) => item.x >= x0 - pad && item.x <= x1 + pad && item.y >= y0 - pad && item.y <= y1 + pad)
    .map((item) => item.str)
    .join(' ')
}

const STOP = new Set([
  'the', 'and', 'for', 'with', 'that', 'this', 'from', 'are', 'was', 'were', 'its', 'has',
  'had', 'have', 'into', 'over', 'under', 'not', 'but', 'you', 'your', 'can', 'will',
  'should', 'than', 'then', 'them', 'they', 'their', 'there', 'would', 'could', 'about',
  'when', 'what', 'which', 'while', 'where', 'after', 'before', 'also', 'one', 'two',
  'use', 'using', 'used', 'how', 'does', 'is', 'it', 'this', 'such', 'these', 'those',
])

export function significantTokens(text: string): string[] {
  return (text.toLowerCase().match(/[a-z0-9]{3,}/g) ?? []).filter((tok) => !STOP.has(tok))
}

function matches(hitToken: string, queryToken: string): boolean {
  const min = Math.min(hitToken.length, queryToken.length)
  if (min >= 4 && (hitToken.startsWith(queryToken) || queryToken.startsWith(hitToken))) return true
  return hitToken === queryToken
}

/** Fraction of `hit`'s significant tokens that appear in `under` (morphology-tolerant). */
export function tokenOverlap(hitText: string, underText: string): number {
  const hitTokens = significantTokens(hitText)
  if (hitTokens.length === 0) return 1
  const underTokens = significantTokens(underText)
  const matched = hitTokens.filter((hit) => underTokens.some((under) => matches(hit, under))).length
  return matched / hitTokens.length
}