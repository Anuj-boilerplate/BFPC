import { useEffect, useRef, useState } from 'react'
import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist'
import type { Highlight } from '../lib/highlights'
import type { ViewportLike } from '../lib/geometry'
import HighlightOverlay from './HighlightOverlay'

interface PageCanvasProps {
  pdf: PDFDocumentProxy
  pageNumber: number
  scale: number
  highlights: Highlight[]
  onError: (message: string) => void
  onViewport: (pageNumber: number, viewport: ViewportLike) => void
  onWrapper: (pageNumber: number, element: HTMLDivElement) => void
}

export default function PageCanvas({ pdf, pageNumber, scale, highlights, onError, onViewport, onWrapper }: PageCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const wrapperRef = useRef<HTMLDivElement>(null)
  const [viewport, setViewport] = useState<ViewportLike | null>(null)

  useEffect(() => {
    let cancelled = false
    let renderTask: RenderTask | undefined

    void (async () => {
      const page = await pdf.getPage(pageNumber)
      if (cancelled) return

      const nextViewport = page.getViewport({ scale })
      const canvas = canvasRef.current
      if (!canvas) return

      canvas.width = Math.floor(nextViewport.width)
      canvas.height = Math.floor(nextViewport.height)
      canvas.style.width = `${nextViewport.width}px`
      canvas.style.height = `${nextViewport.height}px`

      const ctx = canvas.getContext('2d')
      if (!ctx) return

      renderTask = page.render({ canvasContext: ctx, viewport: nextViewport })
      await renderTask.promise
      if (cancelled) return

      if (wrapperRef.current) onWrapper(pageNumber, wrapperRef.current)
      setViewport(nextViewport)
      onViewport(pageNumber, nextViewport)
    })().catch((error: unknown) => {
      onError(error instanceof Error ? error.message : String(error))
    })

    return () => {
      cancelled = true
      renderTask?.cancel()
    }
  }, [pdf, pageNumber, scale, onError, onViewport, onWrapper])

  const pageHighlights = highlights.filter((highlight) => highlight.page === pageNumber)

  return (
    <div
      ref={wrapperRef}
      className="pdf-page"
      data-page-number={pageNumber}
      style={viewport ? { width: viewport.width, height: viewport.height } : undefined}
    >
      <canvas ref={canvasRef} className="pdf-page__canvas" />
      <HighlightOverlay highlights={pageHighlights} viewport={viewport} />
    </div>
  )
}