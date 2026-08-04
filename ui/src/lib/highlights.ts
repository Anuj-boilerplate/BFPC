import type { BBox } from '../api/types'

/** Screen-space highlight anchored to a document page (1-based). */
export interface Highlight {
  page: number
  rects: BBox[] // multiple tight rectangles (replaces single bbox)
  rank: number // 0 = best match, 1 = second best, etc.
}