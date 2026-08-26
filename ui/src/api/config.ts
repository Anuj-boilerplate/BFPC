// Base URL of the BFPC API, per docs/api.md §1.
//
// Production (Docker build): VITE_API_BASE is set to "" so all /api/*
// calls are relative to the same origin as the page — FastAPI serves both.
//
// Local dev: VITE_API_BASE is unset, falling back to the backend dev server.
const _env = import.meta.env.VITE_API_BASE as string | undefined

export const API_BASE_URL: string =
  _env !== undefined
    ? _env.replace(/\/+$/, '')           // production: "" or explicit URL
    : 'http://127.0.0.1:8000'           // local dev: backend on :8000

// Maximum accepted upload size; must match MAX_UPLOAD_BYTES in
// src/bfpc/api/app.py (docs/api.md §3.3).
export const MAX_UPLOAD_BYTES = 100 * 1024 * 1024