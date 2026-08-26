# ── Stage 1: build the React UI ──────────────────────────────────────────────
FROM node:20-slim AS ui-build
WORKDIR /app/ui

COPY ui/package.json ui/package-lock.json* ./
RUN npm ci

COPY ui/ ./

# Empty VITE_API_BASE → API calls use relative paths (/api/...)
# which is correct when FastAPI serves both the UI and the API.
ARG VITE_API_BASE=
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build


# ── Stage 2: Python runtime ───────────────────────────────────────────────────
FROM python:3.11-slim AS runtime
WORKDIR /app

# pydantic uses Rust-compiled extensions; no extra system deps needed for
# pymupdf (ships its own MuPDF binaries) or faiss-cpu (pre-built wheels).
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir -e "."

# Copy the compiled UI into the location FastAPI's StaticFiles mount expects.
COPY --from=ui-build /app/ui/dist ./ui/dist

EXPOSE 8000

# Bind to 0.0.0.0 so Fly.io can reach the process.
CMD ["uvicorn", "bfpc.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
