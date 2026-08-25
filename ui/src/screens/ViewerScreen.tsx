import { useCallback, useState } from 'react'
import { ApiError, askQuestion, documentUrl } from '../api/client'
import type { AnswerResponse, StatusIndexed, TrailItem } from '../api/types'
import AnswerPanel from '../components/AnswerPanel'
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
  const [answer, setAnswer] = useState<AnswerResponse | null>(null)
  const [activeTrailIndex, setActiveTrailIndex] = useState<number | null>(null)
  const [docNonce] = useState(() => Date.now())

  const clearHighlights = useCallback(() => {
    setHighlights([])
    setActiveTrailIndex(null)
  }, [])

  const handleTrailClick = useCallback(
    (index: number, item: TrailItem) => {
      setActiveTrailIndex(index)
      const rects = mergeRects(item.rects)
      if (rects.length === 0) {
        onToast('No highlightable region for this trail item.')
        return
      }
      setHighlights([{ page: item.page, rects, rank: 0 }])
    },
    [onToast],
  )

  const handleSubmit = useCallback(
    async (query: string) => {
      setHighlights([])
      setActiveTrailIndex(null)
      setSearching(true)
      try {
        const response = await askQuestion(query)
        setAnswer(response)
        // Auto-highlight first trail item with rects
        const firstIdx = response.trail.findIndex((t) => t.rects.length > 0)
        if (firstIdx !== -1) {
          const first = response.trail[firstIdx]
          setActiveTrailIndex(firstIdx)
          setHighlights([{ page: first.page, rects: mergeRects(first.rects), rank: 0 }])
        } else if (response.trail.length === 0) {
          // No trail, no highlights
          setHighlights([])
        }
        if (response.status === 'INSUFFICIENT_EVIDENCE') {
          // banner already shows in AnswerPanel; optional toast
        }
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

      <div className="viewer__body viewer__body--split">
        <div className="viewer__answer-column">
          <QueryBar disabled={false} searching={searching} onSubmit={handleSubmit} onEscape={clearHighlights} />
          {answer ? (
            <AnswerPanel response={answer} activeTrailIndex={activeTrailIndex} onTrailClick={handleTrailClick} />
          ) : (
            <div className="viewer__placeholder">
              <p className="viewer__placeholder-text">Ask this document anything to see the answer and evidence trail.</p>
            </div>
          )}
        </div>
        <div className="viewer__pdf-column">
          <PdfViewer url={documentUrl(docNonce)} highlights={highlights} onError={onToast} />
        </div>
      </div>
    </main>
  )
}
