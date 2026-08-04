import { setupWorker } from 'msw/browser'
import pdfUrl from './fixtures/report.pdf?url'
import { createHandlers, createMockState } from './handlers'

const state = createMockState()

export const worker = setupWorker(
  ...createHandlers(state, async () => (await fetch(pdfUrl)).body),
)