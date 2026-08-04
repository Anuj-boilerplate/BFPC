import type { Highlight } from '../lib/highlights'
import { bboxToBox, type ViewportLike } from '../lib/geometry'

interface HighlightOverlayProps {
  highlights: Highlight[]
  viewport: ViewportLike | null
}

/** Draws per-rect highlight boxes across ranked highlights as absolutely-positioned boxes over a page. */
export default function HighlightOverlay({ highlights, viewport }: HighlightOverlayProps) {
  if (!viewport || highlights.length === 0) return null
  return (
    <>
      {highlights.map((highlight, highlightIndex) =>
        highlight.rects.map((bbox, rectIndex) => {
          const box = bboxToBox(bbox, viewport)
          const className = highlight.rank === 0 ? 'highlight' : 'highlight highlight--secondary'
          return (
            <div
              key={`${highlightIndex}-${rectIndex}`}
              className={className}
              data-testid="highlight"
              style={{ left: box.left, top: box.top, width: Math.max(2, box.width), height: Math.max(2, box.height) }}
            />
          )
        }),
      )}
    </>
  )
}