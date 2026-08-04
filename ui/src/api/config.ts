// Base URL of the BFPC API, per docs/api.md §1.
const DEFAULT_API_BASE = 'http://127.0.0.1:8000'

export const API_BASE_URL: string = (
  import.meta.env.VITE_API_BASE as string | undefined
)?.replace(/\/+$/, '') || DEFAULT_API_BASE

// Maximum accepted upload size; must match MAX_UPLOAD_BYTES in
// src/bfpc/api/app.py (docs/api.md §3.3).
export const MAX_UPLOAD_BYTES = 100 * 1024 * 1024