import { readFileSync } from 'node:fs'
import { setupServer } from 'msw/node'
import { createHandlers, createMockState } from './handlers'

export const state = createMockState()

export const server = setupServer(
  ...createHandlers(
    state,
    async () => readFileSync(new URL('./fixtures/report.pdf', import.meta.url)),
  ),
)