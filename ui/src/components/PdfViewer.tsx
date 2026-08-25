import { useCallback, useEffect, useRef, useState } from 'react'
import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist'
import type { PDFDocumentProxy } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.mjs?url'
import type { Highlight } from '../lib/highlights'
import { bboxToBox, type ViewportLike } from '../lib/geometry'
import PageCanvas from './PageCanvas'

GlobalWorkerOptions.workerSrc = workerUrl

interface PdfViewerProps {
  url: string
  highlights: Highlight[]
  onError: (message: string) => void
}

export default function PdfViewer({ url, highlights, onError }: PdfViewerProps) {
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null)
  const [scale, setScale] = useState(1)
  const scrollRef = useRef<HTMLDivElement>(null)
  const viewportsRef = useRef(new Map<number, ViewportLike>())
  const wrappersRef = useRef(new Map<number, HTMLDivElement>())
  const fitDoneRef = useRef(false)
  const highlightsRef = useRef(highlights)
  highlightsRef.current = highlights

  useEffect(() => {
    let cancelled = false
    getDocument({ url })
      .promise.then((doc) => {
        if (cancelled) {
          void doc.destroy()
          return
        }
        setPdf(doc)
      })
      .catch((error: unknown) => {
        onError(error instanceof Error ? error.message : String(error))
      })
    return () => {
      cancelled = true
    }
  }, [url, onError])

  useEffect(() => {
    const loaded = pdf
    return () => {
      void loaded?.destroy()
    }
  }, [pdf])

  const centerHighlight = useCallback(() => {
    const best = highlightsRef.current[0]
    if (!best || best.rects.length === 0) return false
    const viewport = viewportsRef.current.get(best.page)
    const wrapper = wrappersRef.current.get(best.page)
    // Scroll container is the viewer__body (parent of pdfviewer); fall back to document query
    const container = (scrollRef.current?.parentElement as HTMLElement | null)
      ?? (document.querySelector('.viewer__body') as HTMLElement | null)
    if (!viewport || !wrapper || !container) return false

    // Convert each PDF-space rect to CSS pixels relative to the page wrapper,
    // then take the union center so multi-line / multi-rect highlights are
    // truly centered as a single area.
    const boxes = best.rects.map((bbox) => bboxToBox(bbox, viewport))
    const left = Math.min(...boxes.map((b) => b.left))
    const top = Math.min(...boxes.map((b) => b.top))
    const right = Math.max(...boxes.map((b) => b.left + b.width))
    const bottom = Math.max(...boxes.map((b) => b.top + b.height))
    const cx = (left + right) / 2
    const cy = (top + bottom) / 2

    const wrapperRect = wrapper.getBoundingClientRect()
    const containerRect = container.getBoundingClientRect()
    const highlightY = wrapperRect.top + cy
    const highlightX = wrapperRect.left + cx

    const targetTop = container.scrollTop + (highlightY - (containerRect.top + containerRect.height / 2))
    const canScrollX = container.scrollWidth > container.clientWidth + 1
    const targetLeft = canScrollX
      ? container.scrollLeft + (highlightX - (containerRect.left + containerRect.width / 2))
      : container.scrollLeft

    container.scrollTo({ top: targetTop, left: targetLeft, behavior: 'smooth' })
    return true
  }, [])

  const handleViewport = useCallback((pageNumber: number, viewport: ViewportLike) => {
    viewportsRef.current.set(pageNumber, viewport)
    if (!fitDoneRef.current && pageNumber === 1) {
      fitDoneRef.current = true
      const containerWidth = scrollRef.current?.clientWidth ?? 900
      const fitted = (containerWidth - 48) / viewport.width
      setScale(Math.min(2, Math.max(0.5, fitted)))
    }
    if (highlightsRef.current[0]?.page === pageNumber) {
      // Viewport just became available for the highlighted page — center now
      requestAnimationFrame(() => { centerHighlight() })
    }
  }, [centerHighlight])

  const handleWrapper = useCallback((pageNumber: number, element: HTMLDivElement) => {
    wrappersRef.current.set(pageNumber, element)
    if (highlightsRef.current[0]?.page === pageNumber) {
      requestAnimationFrame(() => { centerHighlight() })
    }
  }, [centerHighlight])

  useEffect(() => {
    if (highlights.length === 0) return
    // Defer to next frame so layout (wrapper rects, viewport scale) has settled
    const raf = requestAnimationFrame(() => {
      if (!centerHighlight()) {
        // Viewport/wrapper not ready yet — retry shortly (covers race where
        // search resolves before the page has rendered)
        setTimeout(() => { centerHighlight() }, 80)
        setTimeout(() => { centerHighlight() }, 250)
      }
    })
    // Redundant timeouts handle the case where rAF fired before PageCanvas
    // reported its viewport/wrapper
    const t1 = setTimeout(() => { centerHighlight() }, 80)
    const t2 = setTimeout(() => { centerHighlight() }, 350)
    return () => {
      cancelAnimationFrame(raf)
      clearTimeout(t1)
      clearTimeout(t2)
    }
  }, [highlights, centerHighlight])

  if (!pdf) {
    return (
      <div className="pdfviewer pdfviewer--empty">
        <div className="spinner" role="status" aria-label="Rendering document" />
      </div>
    )
  }

  const pages = Array.from({ length: pdf.numPages }, (_, index) => index + 1)

  return (
    <div className="pdfviewer" ref={scrollRef}>
      <div className="pdfviewer__pages">
        {pages.map((pageNumber) => (
          <PageCanvas
            key={pageNumber}
            pdf={pdf}
            pageNumber={pageNumber}
            scale={scale}
            highlights={highlights}
            onError={onError}
            onViewport={handleViewport}
            onWrapper={handleWrapper}
          />
        ))}
      </div>
      <div className="pdfviewer__zoom">
        <button type="button" aria-label="Zoom out" onClick={() => setScale((s) => Math.max(0.5, s / 1.25))}>−</button>
        <span className="pdfviewer__zoom-label">{Math.round(scale * 100)}%</span>
        <button type="button" aria-label="Zoom in" onClick={() => setScale((s) => Math.min(4, s * 1.25))}>+</button>
      </div>
    </div>
  )
}