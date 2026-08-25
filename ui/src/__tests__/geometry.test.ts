import type { BBox } from '../api/types'
import { bboxToBox, mergeRects } from '../lib/geometry'

describe('bboxToBox', () => {
  it('maps a bbox through a scale-only transform', () => {
    const viewport = { transform: [1.5, 0, 0, 1.5, 0, 0], width: 900, height: 1200 }
    expect(bboxToBox([45, 520, 400, 545], viewport)).toEqual({
      left: 67.5,
      top: 780,
      width: 532.5,
      height: 37.5,
    })
  })

  it('maps a bbox through a translate + scale transform (translation ignored now)', () => {
    const viewport = { transform: [2, 0, 0, 2, 10, 20], width: 1000, height: 1000 }
    expect(bboxToBox([0, 0, 100, 50], viewport)).toEqual({
      left: 0,
      top: 0,
      width: 200,
      height: 100,
    })
  })

  it('handles a 90-degree rotated viewport (scale fallback)', () => {
    // Page 612pt wide rotated 90deg: transform [0, 1, -1, 0, 612, 0].
    const viewport = { transform: [0, 1, -1, 0, 612, 0], width: 792, height: 612 }
    expect(bboxToBox([45, 520, 400, 545], viewport)).toEqual({
      left: 45,
      top: 520,
      width: 355,
      height: 25,
    })
  })
})

describe('mergeRects', () => {
  it('returns an empty list for no rects', () => {
    expect(mergeRects([])).toEqual([])
  })

  it('keeps a single rect as-is', () => {
    expect(mergeRects([[5, 5, 15, 15]])).toEqual([[5, 5, 15, 15]])
  })

  it('unions adjacent word rects on the same line into one continuous box', () => {
    const rects: BBox[] = [
      [10, 20, 30, 30],
      [32, 20, 52, 30],
      [54, 20, 80, 30],
    ]
    expect(mergeRects(rects)).toEqual([[10, 20, 80, 30]])
  })

  it('keeps rects on a different line as separate boxes', () => {
    const rects: BBox[] = [
      [10, 20, 30, 30],
      [32, 20, 52, 30], // same line, tight
      [10, 40, 30, 50], // next line
      [32, 40, 44, 50], // next line, tight
    ]
    expect(mergeRects(rects)).toEqual([
      [10, 20, 52, 30],
      [10, 40, 44, 50],
    ])
  })

  it('splits on a large horizontal gap (sentence break)', () => {
    const rects: BBox[] = [
      [10, 20, 30, 30],
      [90, 20, 110, 30], // gap of 60 >> tolerance
    ]
    expect(mergeRects(rects)).toEqual([
      [10, 20, 30, 30],
      [90, 20, 110, 30],
    ])
  })

  it('merges regardless of input order', () => {
    const rects: BBox[] = [
      [54, 20, 80, 30],
      [10, 20, 30, 30],
      [32, 20, 52, 30],
    ]
    expect(mergeRects(rects)).toEqual([[10, 20, 80, 30]])
  })
})
