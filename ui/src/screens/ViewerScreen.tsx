import { useCallback, useState } from 'react'
import { ApiError, documentUrl, search } from '../api/client'
import type { StatusIndexed } from '../api/types'
import PdfViewer from '../components/PdfViewer'
import QueryBar from '../components/QueryBar'
import { mergeRects } from '../lib/geometry'
import type { Highlight } from '../lib/highlights'

interface ViewerScreenProps {
  status: StatusIndexed
  onToast: (message: string) => void
  onReset: () => void
}

export default function ViewerScreen({ status, onToast, onReset }: ViewerScreenProps) {
  const [highlights, setHighlights] = useState<Highlight[]>([])
  const [searching, setSearching] = useState(false)
  // Stable per-mounted-document: guarantees a fresh GET /api/document after a
  // re-index (the URL path is otherwise constant; see client.documentUrl()).
  const [docNonce] = useState(() => Date.now())

  const clearHighlights = useCallback(() => setHighlights([]), [])

  const handleSubmit = useCallback(
    async (query: string) => {
      setHighlights([])
      setSearching(true)
      try {
        const response = await search(query, 5)
        const top = response.hits[0]
        if (!top) {
          onToast('No matches found for that question.')
          return
        }
        const ranked = response.hits
          .slice(0, 3)
          .map((hit, index) => ({
            page: hit.page,
            rects: mergeRects(hit.rects ?? (hit.bbox ? [hit.bbox] : [])),
            rank: index,
          }))
          .filter((h) => h.rects.length > 0)
        if (ranked.length === 0) {
          onToast('This document source has no highlightable regions (bbox is null).')
          return
        }
        setHighlights(ranked)
      } catch (error) {
        onToast(error instanceof ApiError ? error.message : 'Search failed.')
      } finally {
        setSearching(false)
      }
    },
    [onToast],
  )

  return (
    <main className="viewer">
      <header className="viewer__topbar glass">
        <div className="viewer__doc">
          <span className="viewer__filename" title={status.filename}>
            {status.filename}
          </span>
          <span className="viewer__meta">
            {status.source} · {status.pages} pages · {status.chunks} chunks
          </span>
        </div>
        <button type="button" className="viewer__reset brutal-interactive" onClick={onReset}>
          New document
        </button>
      </header>
      <div className="viewer__body">
        <PdfViewer url={documentUrl(docNonce)} highlights={highlights} onError={onToast} />
      </div>
      <QueryBar disabled={false} searching={searching} onSubmit={handleSubmit} onEscape={clearHighlights} />
    </main>
  )
}