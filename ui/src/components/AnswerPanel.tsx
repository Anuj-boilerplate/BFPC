import type { AnswerResponse, TrailItem } from '../api/types'

const circledNumbers = ['①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩']

interface AnswerPanelProps {
  response: AnswerResponse
  activeTrailIndex: number | null
  onTrailClick: (index: number, item: TrailItem) => void
}

export default function AnswerPanel({ response, activeTrailIndex, onTrailClick }: AnswerPanelProps) {
  const isInsufficient = response.status !== 'COMPLETE'

  return (
    <div className="answer-panel">
      <div className="answer-panel__answer glass">
        <p className="answer-panel__text">{response.answer}</p>
      </div>

      {isInsufficient && (
        <div className="answer-panel__banner" role="alert">
          <span className="answer-panel__banner-icon" aria-hidden="true">
            ⚠
          </span>
          <span>
            <strong>Insufficient evidence</strong>
            {response.missing ? ` — ${response.missing}` : ' — the document does not contain enough evidence to fully answer.'}
          </span>
        </div>
      )}

      {response.trail.length > 0 && (
        <ol className="answer-panel__trail" aria-label="Reading trail">
          {response.trail.map((item, index) => {
            const isActive = activeTrailIndex === index
            return (
              <li
                key={`${item.source_id}-${index}`}
                className={`answer-panel__item${isActive ? ' answer-panel__item--active' : ''}`}
              >
                <div className="answer-panel__item-header">
                  <span className="answer-panel__number" aria-hidden="true">
                    {circledNumbers[index] ?? `${index + 1}.`}
                  </span>
                  <span className="answer-panel__label">{item.label}</span>
                  <span className="answer-panel__source mono">{item.source_id}</span>
                </div>
                <p className="answer-panel__explanation">{item.explanation}</p>
                <button
                  type="button"
                  className="answer-panel__view brutal-interactive"
                  onClick={() => onTrailClick(index, item)}
                  aria-label={`View ${item.label} in document`}
                >
                  View in document →
                </button>
              </li>
            )
          })}
        </ol>
      )}

      {response.trail.length === 0 && (
        <p className="answer-panel__empty">No trail items — answer has no cited sources.</p>
      )}
    </div>
  )
}
