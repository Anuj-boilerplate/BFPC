import { useState, type FormEvent, type KeyboardEvent } from 'react'

interface QueryBarProps {
  disabled: boolean
  searching: boolean
  onSubmit: (query: string) => void
  onEscape: () => void
}

export default function QueryBar({ disabled, searching, onSubmit, onEscape }: QueryBarProps) {
  const [query, setQuery] = useState('')
  const trimmed = query.trim()
  const cannotSubmit = disabled || searching || trimmed === ''

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
    <form className="querybar" onSubmit={handleSubmit}>
      <input
        className="querybar__input"
        type="text"
        placeholder="Ask a question about this document…"
        value={query}
        disabled={disabled || searching}
        aria-label="Question"
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={handleKeyDown}
      />
      <button className="querybar__button" type="submit" disabled={cannotSubmit}>
        {searching ? 'Searching…' : 'Ask'}
      </button>
    </form>
  )
}