"""Phase 10 — Reading trail data model.

Internal Python objects for the ordered reading trail, not wire types.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Bounding box in PDF points: [x0, y0, x1, y1]
BBox = list[float]


@dataclass(frozen=True)
class TrailItem:
    """One step in the ordered reading trail."""

    source_id: str  # e.g. "SOURCE_3"
    role: str  # e.g. "supporting" (from EvidenceNode)
    label: str  # human-readable label, e.g. "Evidence"
    explanation: str  # one sentence: why this source matters
    page: int  # 1-based PDF page (from LLMContext.original)
    rects: list[BBox]  # tight highlight rects; [] if none


@dataclass(frozen=True)
class ReadingTrail:
    """Ordered minimal trail (not every graph node)."""

    items: list[TrailItem]
