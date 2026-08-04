import '@testing-library/jest-dom/vitest'
import { afterAll, afterEach, beforeAll } from 'vitest'
import { server, state } from '../mocks/server'
import { resetMockState } from '../mocks/handlers'

beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' })
})

afterEach(() => {
  server.resetHandlers()
  resetMockState(state)
})

afterAll(() => {
  server.close()
})
