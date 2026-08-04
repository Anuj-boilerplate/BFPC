import { useState } from 'react'
import { ApiError, indexDocument } from '../api/client'
import type { IndexResponse } from '../api/types'
import Dropzone from '../components/Dropzone'

interface UploadScreenProps {
  onIndexed: (response: IndexResponse) => void
  onToast: (message: string) => void
  onBack?: () => void
}

export default function UploadScreen({ onIndexed, onToast, onBack }: UploadScreenProps) {
  const [busy, setBusy] = useState(false)

  const handleFile = async (file: File) => {
    setBusy(true)
    try {
      const response = await indexDocument(file)
      onIndexed(response)
    } catch (error) {
      onToast(error instanceof ApiError ? error.message : 'Upload failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="upload">
      <header className="upload__header">
        <h1 className="upload__title">BFPC</h1>
        <p className="upload__subtitle">
          Blazing Fast PDF Companion — upload a document, ask a question, and get the answer highlighted right on the page.
        </p>
      </header>
      <Dropzone busy={busy} onFile={handleFile} onToast={onToast} />
      {onBack && (
        <button type="button" className="upload__back" onClick={onBack}>
          Cancel — keep the current document
        </button>
      )}
    </main>
  )
}