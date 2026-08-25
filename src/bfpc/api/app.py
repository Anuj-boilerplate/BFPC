"""FastAPI application exposing the BFPC API contract.

Endpoints (exactly the four from ``docs/api.md`` §1):

- ``POST /api/index``    multipart upload -> parse/chunk/embed/index
- ``GET  /api/status``   current active document summary
- ``POST /api/search``   vector search over the active document
- ``GET  /api/document`` raw bytes of the active document
"""

from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware

from bfpc.api.schemas import SearchRequest, SearchResponse
from bfpc.api.service import (
    ApiError,
    IndexFailed,
    IndexService,
    NoActiveDocument,
    UnsupportedExtension,
    ZeroChunks,
)

#: Allowed dev origins (contract §7).
_ALLOWED_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")

#: Maximum accepted upload size (contract §3.3); enforced before parsing.
MAX_UPLOAD_BYTES = 100 * 1024 * 1024

#: Serializes index replacement so a swap never interleaves (contract §7).
_LOCK = asyncio.Lock()


def create_app(service: IndexService | None = None) -> FastAPI:
    """Build the application.

    ``service`` is injectable for tests; the default wires the real embedder.
    """
    if service is None:
        from bfpc.index.embedder import Embedder

        service = IndexService(Embedder())

    app = FastAPI(title="BFPC API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(_ALLOWED_ORIGINS),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    # Every response that isn't a 2xx body must be exactly {"detail": "..."}.
    @app.exception_handler(RequestValidationError)
    async def _on_validation_error(request: Request, exc: RequestValidationError) -> Response:
        return _detail_response(_first_validation_message(exc), 422)

    @app.exception_handler(ResponseValidationError)
    async def _on_response_validation_error(request: Request, exc: ResponseValidationError) -> Response:
        # Retrieval output violated the frozen §5.2 shape (a hit missing a
        # required field): reject with the standard internal-error envelope.
        return _detail_response("internal error", 500)

    @app.exception_handler(ApiError)
    async def _on_api_error(request: Request, exc: ApiError) -> Response:
        return _detail_response(exc.message, _status_for(exc))

    @app.exception_handler(Exception)
    async def _on_unexpected(request: Request, exc: Exception) -> Response:
        return _detail_response("internal error", 500)

    @app.get("/api/status")
    async def status() -> dict:
        return service.status()

    @app.post("/api/index")
    async def index_file(request: Request) -> Response:
        try:
            contents, filename = _validate_upload(await request.form())
        except _UploadRejected as exc:
            return _detail_response(exc.detail, exc.status)
        # Parsing/chunking/embedding is CPU-bound; run it in the thread pool
        # so the event loop stays responsive (status/search keep working).
        async with _LOCK:
            try:
                result = await asyncio.to_thread(service.index, contents, filename)
            except (UnsupportedExtension, ZeroChunks, IndexFailed) as exc:
                return _detail_response(exc.message, _status_for(exc))
        return _json_response(result)

    @app.post("/api/search", response_model=SearchResponse)
    async def search(payload: SearchRequest) -> dict:
        # Query embedding is model inference; keep it off the event loop.
        return await asyncio.to_thread(service.search, payload.query, payload.top_k)

    @app.get("/api/document")
    async def document() -> Response:
        raw, content_type, filename = service.document()
        return Response(
            content=raw,
            headers={
                "Content-Type": content_type,
                "Content-Disposition": f'inline; filename="{filename}"',
                # The document URL is constant across re-indexes; never let a
                # browser or pdf.js cache serve stale bytes after a swap.
                "Cache-Control": "no-store",
            },
        )

    return app


app = create_app()


class _UploadRejected(Exception):
    """Raised by ``_validate_upload`` for malformed or oversized uploads."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _validate_upload(form) -> tuple[bytes, str]:
    """Validate the multipart form strictly (contract §3.1, §3.3)."""
    names = {name for name, _ in form.multi_items()}
    if names != {"file"}:
        raise _UploadRejected(422, "expected exactly one form field named 'file'")
    upload = form["file"]
    if isinstance(upload, str):
        raise _UploadRejected(422, "the 'file' part must be a file upload")
    filename = upload.filename
    if not filename:
        raise _UploadRejected(422, "file part must include a filename")
    contents = upload.file.read(MAX_UPLOAD_BYTES + 1)
    if not contents:
        raise _UploadRejected(422, "file part is empty")
    if len(contents) > MAX_UPLOAD_BYTES:
        limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        raise _UploadRejected(422, f"file exceeds the {limit_mb} MB upload limit")
    return contents, filename


def _status_for(exc: ApiError) -> int:
    if isinstance(exc, (UnsupportedExtension, ZeroChunks)):
        return 400
    if isinstance(exc, NoActiveDocument):
        return 409
    return 500


def _detail_response(detail: str, status: int) -> Response:
    body = json.dumps(jsonable_encoder({"detail": detail}))
    return Response(content=body, status_code=status, media_type="application/json")


def _json_response(obj: object) -> Response:
    return Response(
        content=json.dumps(jsonable_encoder(obj)),
        media_type="application/json",
    )


def _first_validation_message(exc: RequestValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "invalid request"
    first = errors[0]
    loc = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
    message = first.get("msg", "invalid")
    return f"{loc}: {message}" if loc else message
