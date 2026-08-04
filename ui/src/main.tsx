import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { worker } from './mocks/browser'
import './app.css'

async function enableMocking(): Promise<void> {
  const mockEnabled = import.meta.env.VITE_API_MOCK === '1'
  if (mockEnabled) {
    await worker.start({ onUnhandledRequest: 'bypass' })
  }
}

enableMocking().then(() => {
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  )
})
