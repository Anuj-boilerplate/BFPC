import type { BBox } from '../api/types'

/** Subset of pdf.js PageViewport we depend on. */
export interface ViewportLike {
  transform: number[]
  width: number
  height: number
}

export interface Box {
  left: number
  top: number
  width: number
  height: number
}

/**
 * Map a chunk bounding box from PyMuPDF to CSS pixels.
 *
 * PyMuPDF bboxes use top-left origin with Y increasing downward,
 * matching CSS coordinate space. We extract the scale factor and map directly.
 */
export function bboxToBox(bbox: BBox, viewport: ViewportLike): Box {
  // PyMuPDF bboxes use top-left origin with Y increasing downward,
  // matching CSS coordinate space. The pdf.js viewport transform expects
  // bottom-left origin (Y-up) PDF user-space coordinates, so feeding
  // PyMuPDF coords through it double-flips the Y axis.
  //
  // Instead we extract the scale factor and map directly.
  const scale = Math.abs(viewport.transform[0]) || 1
  const [x0, y0, x1, y1] = bbox
  return {
    left: x0 * scale,
    top: y0 * scale,
    width: (x1 - x0) * scale,
    height: (y1 - y0) * scale,
  }
}

/**
 * Merge per-word rectangles into continuous per-line highlight boxes.
 *
 * Word rects are precise but visually fragmented. Rects on the same
 * visual line whose horizontal gap is at most half the average rect
 * height are unioned into one box; a new box starts when the line
 * changes or the gap is too large (e.g. a sentence break).
 */
export function mergeRects(rects: BBox[]): BBox[] {
  if (rects.length === 0) return []
  const averageHeight =
      rects.reduce((sum, [, y0, , y1]) => sum + (y1 - y0), 0) / rects.length
  const tolerance = Math.max(1, averageHeight / 2)
  const sorted = [...rects].sort((a, b) => a[1] - b[1] || a[0] - b[0])

  const merged: BBox[] = []
  let [x0, y0, x1, y1] = sorted[0]
  const centerY = (r: BBox) => (r[1] + r[3]) / 2

  for (const rect of sorted.slice(1)) {
    const sameLine = Math.abs(centerY(rect) - (y0 + y1) / 2) <= tolerance
    const gap = rect[0] - x1
    if (sameLine && gap <= tolerance) {
      x0 = Math.min(x0, rect[0])
      x1 = Math.max(x1, rect[2])
      y0 = Math.min(y0, rect[1])
      y1 = Math.max(y1, rect[3])
    } else {
      merged.push([x0, y0, x1, y1])
      ;[x0, y0, x1, y1] = rect
    }
  }
  merged.push([x0, y0, x1, y1])
  return merged
}