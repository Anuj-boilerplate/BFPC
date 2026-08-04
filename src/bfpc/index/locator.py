"""Locate snippet bounding rectangles on PDF pages via PyMuPDF text search.

The highlight layer needs exact page coordinates for a snippet. PyMuPDF's
``Page.search_for`` already handles cross-line and approximate matches,
but block-extracted text contains newlines and irregular whitespace, so
the snippet is whitespace-normalized first. Out-of-range pages are
treated as "not found" and yield ``[]``; genuine errors (e.g. corrupt
PDF bytes) are left to the caller.
"""

from __future__ import annotations

import re

import pymupdf

_FALLBACK_LENGTH = 80


def locate_text(
    pdf_bytes: bytes,
    page_number: int,
    snippet: str,
) -> list[tuple[float, float, float, float]]:
    """Find exact bounding rectangles for snippet on the given page.

    Page numbers are 1-based, matching the :class:`Chunk` model. If the
    snippet cannot be found, its first :data:`_FALLBACK_LENGTH`
    characters are retried in case the snippet outgrew its source text.

    :param pdf_bytes: PDF file contents.
    :param page_number: 1-based page number.
    :param snippet: text to locate on the page.
    :return: ``(x0, y0, x1, y1)`` rectangles for every match, or ``[]``.
    """
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        if page_number < 1 or page_number > doc.page_count:
            return []
        page = doc[page_number - 1]
        text = re.sub(r"\s+", " ", snippet).strip()
        rects = page.search_for(text)
        if not rects:
            rects = page.search_for(text[:_FALLBACK_LENGTH])
        return [(r.x0, r.y0, r.x1, r.y1) for r in rects]
