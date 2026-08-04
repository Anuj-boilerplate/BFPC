"""Pydantic request/response models for the HTTP API.

These models are the wire contract from ``docs/api.md``. ``IndexResponse``
and ``StatusResponse`` are produced by the service as plain dicts because
their key sets are conditionally null; only the search request needs
strict validation (``extra="forbid"`` makes unknown fields a 422).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Bounding box: four PDF points (x0, y0, x1, y1), top-left origin.
BBox = list[float]


class SearchRequest(BaseModel):
    """Request body for ``POST /api/search`` (contract §5.1)."""

    model_config = ConfigDict(extra="forbid")

    query: str
    top_k: int = Field(default=5, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def _query_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("query must not be blank")
        return stripped


class Hit(BaseModel):
    """One retrieval result (contract §5.2)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    text: str
    page: int
    kind: str
    score: float
    bbox: BBox | None
    snippet: str | None = None   # NEW: the best-matching sentence
    rects: list[BBox] | None = None  # NEW: tight rectangles for the snippet


class SearchResponse(BaseModel):
    """Response body for ``POST /api/search`` (contract §5.2)."""

    model_config = ConfigDict(extra="ignore")

    query: str
    top_k: int
    hits: list[Hit]