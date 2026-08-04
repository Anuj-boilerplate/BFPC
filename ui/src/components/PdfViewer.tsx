import { useCallback, useEffect, useRef, useState } from 'react'
import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist'
import type { PDFDocumentProxy } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.mjs?url'
import type { Highlight } from '../lib/highlights'
import type { ViewportLike } from '../lib/geometry'
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

  const handleViewport = useCallback((pageNumber: number, viewport: ViewportLike) => {
    viewportsRef.current.set(pageNumber, viewport)
    if (!fitDoneRef.current && pageNumber === 1) {
      fitDoneRef.current = true
      const containerWidth = scrollRef.current?.clientWidth ?? 900
      const fitted = (containerWidth - 48) / viewport.width
      setScale(Math.min(2, Math.max(0.5, fitted)))
    }
  }, [])

  const handleWrapper = useCallback((pageNumber: number, element: HTMLDivElement) => {
    wrappersRef.current.set(pageNumber, element)
  }, [])

  useEffect(() => {
    const best = highlights[0]
    if (!best) return
    wrappersRef.current.get(best.page)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [highlights])

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