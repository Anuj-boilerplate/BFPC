"""PDF reader backed by PyMuPDF.

PyMuPDF is used rather than PDFium because it ships as a prebuilt wheel,
offers sorted block extraction, and exposes the per-block coordinates the
rest of BFPC needs for highlighting and search.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

from bfpc.parser.models import Block, BlockKind, Document, Page, Source

_HEADING_SIZE_RATIO = 1.2

#: PyMuPDF ``get_text("blocks")`` block type codes (0 = text, 1 = image).
_BLOCK_TYPE_IMAGE = 1


class PdfReader:
    """Parse a PDF into a :class:`Document` using PyMuPDF."""

    def read(self, path: Path) -> Document:
        """Parse ``path`` and return its document model.

        :param path: path to a PDF file.
        :return: the parsed document.
        :raises FileNotFoundError: if the file does not exist.
        :raises ValueError: if the file cannot be opened as a PDF.
        """
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"PDF not found: {path}")

        try:
            with pymupdf.open(path) as pdf:
                return self._parse(pdf, path)
        except pymupdf.FileDataError as exc:
            raise ValueError(f"Not a valid PDF: {path}") from exc

    def _parse(self, pdf: pymupdf.Document, path: Path) -> Document:
        pages: list[Page] = []
        for number, page in enumerate(pdf, start=1):
            blocks = self._extract_blocks(page, number)
            pages.append(Page(number=number, blocks=blocks))

        return Document(
            path=path,
            source=Source.PDF,
            pages=pages,
            metadata=self._metadata(pdf),
        )

    @staticmethod
    def _metadata(pdf: pymupdf.Document) -> dict:
        meta = pdf.metadata or {}
        return {
            "title": meta.get("title", "") or "",
            "author": meta.get("author", "") or "",
            "subject": meta.get("subject", "") or "",
            "page_count": pdf.page_count,
        }

    def _extract_blocks(self, page: pymupdf.Page, page_number: int) -> list[Block]:
        table_rects = _detect_tables(page)
        body_size = _dominant_font_size(page)
        block_font_sizes = _max_font_size_per_block(page)

        blocks: list[Block] = []
        for item in page.get_text("blocks", sort=True):
            x0, y0, x1, y1, text, block_no, block_type = item
            bbox = (float(x0), float(y0), float(x1), float(y1))

            if block_type == _BLOCK_TYPE_IMAGE:
                blocks.append(Block(text="", source=Source.PDF, kind=BlockKind.IMAGE, bbox=bbox))
                continue

            if not text.strip():
                continue

            max_font = block_font_sizes.get(block_no, body_size)
            blocks.append(
                Block(
                    text=text.strip(),
                    source=Source.PDF,
                    kind=_classify_block(text, bbox, table_rects, max_font, body_size),
                    bbox=bbox,
                )
            )
        return blocks


def _detect_tables(page: pymupdf.Page) -> list[tuple[float, float, float, float]]:
    """Return bounding boxes of any tables PyMuPDF can find on the page."""
    try:
        tables = page.find_tables()
    except Exception:
        return []
    return [tuple(t.bbox) for t in tables.tables]


def _dominant_font_size(page: pymupdf.Page) -> float:
    """Return the median span font size as the body-text baseline.

    Median is used instead of the mode: on a page with one heading and one
    body span the mode ties, which could select the heading size and then
    suppress all heading detection.
    """
    sizes: list[float] = []
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                size = span.get("size")
                if size:
                    sizes.append(round(size, 1))
    if not sizes:
        return 0.0
    ordered = sorted(sizes)
    midpoint = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2.0


def _max_font_size_per_block(page: pymupdf.Page) -> dict[int, float]:
    """Map PyMuPDF block numbers to the largest font size found inside them."""
    result: dict[int, float] = {}
    for block in page.get_text("dict").get("blocks", []):
        max_size = 0.0
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                size = span.get("size")
                if size:
                    max_size = max(max_size, size)
        if max_size:
            result[block["number"]] = max_size
    return result


def _classify_block(
    text: str,
    bbox: tuple[float, float, float, float],
    table_rects: list[tuple[float, float, float, float]],
    max_font_size: float,
    body_size: float,
) -> BlockKind:
    """Pick a semantic kind for a text block using cheap heuristics."""
    if _overlaps_table(bbox, table_rects):
        return BlockKind.TABLE
    if max_font_size and body_size and max_font_size > body_size * _HEADING_SIZE_RATIO:
        return BlockKind.HEADING
    if _looks_like_list(text):
        return BlockKind.LIST
    return BlockKind.TEXT


def _overlaps_table(
    bbox: tuple[float, float, float, float],
    table_rects: list[tuple[float, float, float, float]],
) -> bool:
    """True if ``bbox`` overlaps any detected table region."""
    x0, y0, x1, y1 = bbox
    for t in table_rects:
        tx0, ty0, tx1, ty1 = t
        if x0 < tx1 and x1 > tx0 and y0 < ty1 and y1 > ty0:
            return True
    return False


def _looks_like_list(text: str) -> bool:
    """True if the block begins with a bullet or numbered-list marker."""
    first_line = text.splitlines()[0].strip() if text else ""
    return (
        first_line.startswith(("-", "•", "*", "◦"))
        or (len(first_line) > 1 and first_line[0].isdigit() and first_line[1] in ". )")
    )
