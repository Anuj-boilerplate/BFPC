import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, getStatus } from './api/client'
import type { IndexResponse, StatusIndexed } from './api/types'
import Toasts, { type Toast } from './components/Toasts'
import UploadScreen from './screens/UploadScreen'
import ViewerScreen from './screens/ViewerScreen'

type Screen =
  | { name: 'loading' }
  | { name: 'upload'; previous: StatusIndexed | null }
  | { name: 'viewer'; status: StatusIndexed }

export default function App() {
  const [screen, setScreen] = useState<Screen>({ name: 'loading' })
  const [toasts, setToasts] = useState<Toast[]>([])
  const toastTimeoutRef = useRef<number | null>(null)

  const toast = useCallback((message: string, variant: 'error' | 'success' = 'error') => {
    if (toastTimeoutRef.current) {
      window.clearTimeout(toastTimeoutRef.current)
    }
    const id = Date.now() + Math.random()
    setToasts((current) => [...current, { id, message, variant }])
    toastTimeoutRef.current = window.setTimeout(() => {
      setToasts([])
      toastTimeoutRef.current = null
    }, 4000)
  }, [])

  useEffect(() => {
    return () => {
      if (toastTimeoutRef.current) {
        window.clearTimeout(toastTimeoutRef.current)
      }
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    getStatus()
      .then((status) => {
        if (cancelled) return
        setScreen(status.indexed ? { name: 'viewer', status } : { name: 'upload', previous: null })
      })
      .catch((error: unknown) => {
        if (cancelled) return
        toast(error instanceof ApiError ? error.message : 'Failed to reach the BFPC server.')
        setScreen({ name: 'upload', previous: null })
      })
    return () => {
      cancelled = true
    }
  }, [toast])

  const handleIndexed = useCallback((response: IndexResponse) => {
    setScreen({
      name: 'viewer',
      status: {
        indexed: true,
        filename: response.filename,
        source: response.source,
        pages: response.pages,
        chunks: response.chunks,
      },
    })
  }, [])

  if (screen.name === 'loading') {
    return (
      <main className="loading-screen">
        <div className="spinner" aria-label="Connecting to BFPC server" />
      </main>
    )
  }

  return (
    <>
      {screen.name === 'upload' ? (
        <UploadScreen
          onIndexed={handleIndexed}
          onToast={toast}
          onBack={
            screen.previous ? () => setScreen({ name: 'viewer', status: screen.previous as StatusIndexed }) : undefined
          }
        />
      ) : (
        <ViewerScreen status={screen.status} onToast={toast} onReset={() => setScreen({ name: 'upload', previous: screen.status })} />
      )}
      <Toasts toasts={toasts} />
    </>
  )
}
