import { useState, type FormEvent, type KeyboardEvent } from 'react'

interface QueryBarProps {
  disabled: boolean
  searching: boolean
  onSubmit: (query: string) => void
  onEscape: () => void
}

export default function QueryBar({ disabled, searching, onSubmit, onEscape }: QueryBarProps) {
  const [query, setQuery] = useState('')
  const [focused, setFocused] = useState(false)
  const trimmed = query.trim()
  const cannotSubmit = disabled || searching || trimmed === ''

  const formClass =
    'querybar' + (focused ? ' querybar--focused' : '') + (searching ? ' querybar--searching' : '')

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (cannotSubmit) return
    onSubmit(trimmed)
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Escape') {
      setQuery('')
      onEscape()
    }
  }

  return (
    <form className={formClass} onSubmit={handleSubmit}>
      <span className="querybar__input-wrap">
        <input
          className="querybar__input"
          type="text"
          placeholder="Ask this document anything..."
          value={query}
          disabled={disabled || searching}
          aria-label="Question"
          onChange={(event) => setQuery(event.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onKeyDown={handleKeyDown}
        />
      </span>
      <button
        className="querybar__button"
        type="submit"
        disabled={cannotSubmit}
        aria-label="Ask"
      >
        {searching ? <span className="querybar__spinner" aria-hidden="true" /> : 'Ask'}
      </button>
    </form>
  )
}
