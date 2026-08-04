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