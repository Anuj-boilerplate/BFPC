import { bboxToBox } from '../lib/geometry'

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
