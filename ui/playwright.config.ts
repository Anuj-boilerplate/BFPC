import { defineConfig } from '@playwright/test'

/**
 * End-to-end suite: the UI in a real Chromium browser against the real BFPC
 * backend (system python, uvicorn on 127.0.0.1:8000) — NOT the MSW mock.
 *
 * - `workers: 1` because the backend holds a single active document (§2.1).
 * - Servers are typically pre-started by `ui/e2e/run.ps1` (which warms
 *   report.pdf into the backend so the suite runs in minutes, not tens);
 *   `reuseExistingServer` keeps a manually started stack alive and boots a
 *   fresh one when none is running (cold mode: the first report.pdf index
 *   takes several CPU minutes).
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 600_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report' }],
  ],
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    viewport: { width: 1440, height: 900 },
  },
  webServer: [
    {
      command: 'python -m uvicorn bfpc.api.app:app --host 127.0.0.1 --port 8000',
      cwd: '..',
      url: 'http://127.0.0.1:8000/api/status',
      reuseExistingServer: true,
      timeout: 60_000,
    },
    {
      command: 'npm run dev',
      cwd: '.',
      url: 'http://localhost:5173',
      reuseExistingServer: true,
      timeout: 60_000,
    },
  ],
})
