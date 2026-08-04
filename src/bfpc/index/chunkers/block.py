"""Block-level chunker: one chunk per parser block, with structure merging.

Each parser block becomes a single retrievable chunk, preserving the
block's bounding box for precise highlight targeting.  Three structural
passes reduce the number of chunks (and therefore embedding + index
cost) without sacrificing retrieval precision:

1. **Table rows**: PyMuPDF emits each table cell as its own block, so a
   table contributes dozens of tiny single-cell chunks.  Cells whose
   vertical bands overlap are re-grouped by row: one chunk per row, with
   the row's union bbox.  Highlight precision stays row-tight instead of
   cell-fragmented.
2. **List items**: consecutive ``LIST`` blocks on a page are merged into
   one chunk (union bbox) as long as the merged text stays under
   ``MAX_CHUNK_CHARS``.
3. **Noise filter**: text blocks whose stripped length is under
   ``MIN_TEXT_CHARS`` are dropped — single-char/whitespace cells produce
   weak, throwaway embeddings.

Blocks that exceed the ~500-token ceiling (``MAX_CHUNK_CHARS``) are
split at sentence boundaries while retaining the original bbox on each
sub-chunk.
"""

from __future__ import annotations

import re

from bfpc.index.chunker import MAX_CHUNK_CHARS, Chunk, register
from bfpc.parser.models import Block, BlockKind, Document

# Sentence boundary pattern: matches '.', '!', '?' followed by whitespace
# or end of string.  We keep the delimiter attached to the preceding
# sentence so reconstruction is lossless.
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

#: Smallest stripped text worth keeping as its own chunk.
MIN_TEXT_CHARS = 3


# ---------------------------------------------------------------------------
# Text + geometry helpers
# ---------------------------------------------------------------------------


def _split_sentences(text: str) -> list[str]:
    """Split *text* into sentences using a simple heuristic."""
    return _SENTENCE_RE.split(text)


def _union(
    bbox_a: tuple[float, float, float, float] | None,
    bbox_b: tuple[float, float, float, float] | None,
) -> tuple[float, float, float, float] | None:
    """Union two bounding boxes; ``None`` inputs degrade to the other."""
    if bbox_a is None:
        return bbox_b
    if bbox_b is None:
        return bbox_a
    return (
        min(bbox_a[0], bbox_b[0]),
        min(bbox_a[1], bbox_b[1]),
        max(bbox_a[2], bbox_b[2]),
        max(bbox_a[3], bbox_b[3]),
    )


def _row_bottom(blocks: list[Block]) -> float | None:
    """Lowest bottom edge across *blocks*."""
    bottoms = [b.bbox[3] for b in blocks if b.bbox is not None]
    return max(bottoms) if bottoms else None


def _starts_below(block: Block, rows: list[Block]) -> bool:
    """True if *block*'s top edge sits below the running row's bottom edge."""
    if block.bbox is None:
        return False
    if not rows:
        return False
    tops = [b.bbox[1] for b in rows if b.bbox is not None]
    if not tops:
        return False
    row_top = min(tops)
    bottom = _row_bottom(rows)
    if bottom is None:
        return False
    row_height = bottom - row_top
    return block.bbox[1] > row_top + row_height * 0.5


def _join_text(blocks: list[Block]) -> str:
    """Concatenate the stripped text of *blocks* with single spaces."""
    return " ".join(b.text.strip() for b in blocks if b.text.strip())


def _union_bbox(blocks: list[Block]) -> tuple[float, float, float, float] | None:
    """Union the bboxes of *blocks* in order."""
    bbox = None
    for block in blocks:
        bbox = _union(bbox, block.bbox)
    return bbox


# ---------------------------------------------------------------------------
# Chunk construction
# ---------------------------------------------------------------------------


def _chunks_from_text(
    text: str,
    bbox: tuple[float, float, float, float] | None,
    page_number: int,
    unit_index: int,
    source: str,
    kind: str,
) -> list[Chunk]:
    """Turn a text unit (row, paragraph, heading, merged list) into Chunks."""
    text = text.strip()
    if not text:
        return []

    # Fast path: fits in one chunk
    if len(text) <= MAX_CHUNK_CHARS:
        return [
            Chunk(
                id=f"{page_number}-{unit_index}",
                text=text,
                page=page_number,
                source=source,
                bbox=bbox,
                kind=kind,
            )
        ]

    # Slow path: split at sentence boundaries
    sentences = _split_sentences(text)
    chunks: list[Chunk] = []
    current = ""
    sub_idx = 0

    for sentence in sentences:
        if current and len(current) + len(sentence) + 1 > MAX_CHUNK_CHARS:
            chunks.append(
                Chunk(
                    id=f"{page_number}-{unit_index}.{sub_idx}",
                    text=current.strip(),
                    page=page_number,
                    source=source,
                    bbox=bbox,
                    kind=kind,
                )
            )
            sub_idx += 1
            current = sentence
        else:
            current = f"{current} {sentence}".strip() if current else sentence

    if current.strip():
        chunks.append(
            Chunk(
                id=f"{page_number}-{unit_index}.{sub_idx}",
                text=current.strip(),
                page=page_number,
                source=source,
                bbox=bbox,
                kind=kind,
            )
        )

    return chunks


def _chunk_page(page, chunks: list[Chunk], unit_index: list[int], source: str) -> None:
    """Emit :class:`Chunk` objects for *page* into *chunks* (document order)."""
    table_row: list[Block] | None = None
    text_run: list[Block] | None = None

    def emit_text_run() -> None:
        nonlocal text_run
        if not text_run:
            return
        kind = text_run[0].kind.value
        bbox = _union_bbox(text_run)
        chunks.extend(
            _chunks_from_text(
                _join_text(text_run), bbox, page.number, unit_index[0], source, kind
            )
        )
        unit_index[0] += 1
        text_run = None

    def emit_table_row() -> None:
        nonlocal table_row
        if not table_row:
            return
        chunks.extend(
            _chunks_from_text(
                _join_text(table_row),
                _union_bbox(table_row),
                page.number,
                unit_index[0],
                source,
                "table",
            )
        )
        unit_index[0] += 1
        table_row = None

    for block in page.blocks:
        if block.kind == BlockKind.IMAGE:
            continue
        if not block.text.strip():
            continue

        if block.kind == BlockKind.TABLE:
            if table_row is not None and not _starts_below(block, table_row):
                table_row.append(block)
            else:
                emit_text_run()
                emit_table_row()
                table_row = [block]
            continue

        # Non-table block
        if len(block.text.strip()) < MIN_TEXT_CHARS:
            continue  # too short to embed usefully

        emit_table_row()

        if (
            block.kind == BlockKind.LIST
            and text_run is not None
            and text_run[0].kind == BlockKind.LIST
            and len(_join_text(text_run)) + len(block.text.strip()) + 1 <= MAX_CHUNK_CHARS
        ):
            text_run.append(block)
        else:
            emit_text_run()
            text_run = [block]

    emit_text_run()
    emit_table_row()


@register("block")
def chunk_block(document: Document) -> list[Chunk]:
    """Chunk a document: one chunk per parser block, merged where cheap.

    :param document: parsed document.
    :return: list of :class:`Chunk` objects, in document order.
    """
    chunks: list[Chunk] = []
    for page in document.pages:
        unit_index = [0]
        _chunk_page(page, chunks, unit_index, document.source.value)
    return chunks