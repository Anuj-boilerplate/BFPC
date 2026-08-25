import { useRef, useState, type KeyboardEvent } from 'react'
import { MAX_UPLOAD_BYTES } from '../api/config'

interface DropzoneProps {
  busy: boolean
  onFile: (file: File) => void
  onToast: (message: string) => void
}

export default function Dropzone({ busy, onFile, onToast }: DropzoneProps) {
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const acceptFile = (files: FileList | null) => {
    const file = files?.[0]
    if (!file) return
    if (!/\.pdf$/i.test(file.name)) {
      onToast('Only PDF files are supported in the UI.')
      return
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      onToast(`File is larger than the ${MAX_UPLOAD_BYTES / (1024 * 1024)} MB upload limit.`)
      return
    }
    onFile(file)
  }

  const openPicker = () => {
    if (!busy) inputRef.current?.click()
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (busy) return
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      openPicker()
    }
  }

  return (
    <div
      className={`dropzone glass brutal-interactive${dragging ? ' dropzone--drag' : ''}${busy ? ' dropzone--busy' : ''}`}
      role="button"
      tabIndex={0}
      aria-label="Upload a PDF document"
      onClick={openPicker}
      onKeyDown={handleKeyDown}
      onDragOver={(event) => {
        event.preventDefault()
        if (!busy) setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault()
        setDragging(false)
        if (!busy) acceptFile(event.dataTransfer.files)
      }}
    >
      <input
        ref={inputRef}
        className="dropzone__input"
        type="file"
        accept=".pdf"
        onChange={(event) => {
          acceptFile(event.target.files)
          event.target.value = ''
        }}
      />
      {busy ? (
        <div className="dropzone__busy">
          <div className="spinner" aria-label="Indexing" />
          <p className="dropzone__title">Processing...</p>
          <p className="dropzone__hint">It is being parsed, chunked, embedded, and indexed. The first run also loads the embedding model, so this can take a minute.</p>
        </div>
      ) : (
        <>
          <svg className="dropzone__icon" viewBox="0 0 24 24" width="36" height="36" aria-hidden="true">
            <path d="M12 16V4m0 0 5 5m-5-5-5 5M5 20h14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <p className="dropzone__title">Drop a PDF, Markdown, or Word file</p>
          <p className="dropzone__hint">or click to browse</p>
        </>
      )}
    </div>
  )
}