"""Unit tests for the chunking layer (no model, no fixtures)."""

from __future__ import annotations

import pytest

from bfpc.index.chunker import MAX_CHUNK_CHARS, Chunk, REGISTRY, register
from bfpc.index.chunkers.block import chunk_block
from bfpc.parser.models import Block, BlockKind, Document, Page, Source


def _pdf_block(
    text: str,
    kind: BlockKind = BlockKind.TEXT,
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 100.0, 10.0),
) -> Block:
    return Block(text=text, source=Source.PDF, kind=kind, bbox=bbox)


def _document(pages: list[list[Block]]) -> Document:
    return Document(
        path=__file__,
        source=Source.PDF,
        pages=[Page(number=i + 1, blocks=blocks) for i, blocks in enumerate(pages)],
    )


class TestChunkValidation:
    def test_empty_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            Chunk(id="", text="hello", page=1, source="pdf")

    def test_zero_page_rejected(self) -> None:
        with pytest.raises(ValueError, match="1-based"):
            Chunk(id="c1", text="hello", page=0, source="pdf")

    def test_blank_text_rejected(self) -> None:
        with pytest.raises(ValueError, match="no text"):
            Chunk(id="c1", text="   ", page=1, source="pdf")


class TestRegistry:
    def test_duplicate_registration_rejected(self) -> None:
        def _chunker(document):  # pragma: no cover - never invoked
            return []

        register("duplicate-test")(_chunker)
        with pytest.raises(ValueError, match="already registered"):
            register("duplicate-test")(_chunker)
        del REGISTRY["duplicate-test"]

    def test_block_chunker_registered(self) -> None:
        assert "block" in REGISTRY


class TestBlockChunker:
    def test_one_chunk_per_block(self) -> None:
        document = _document(
            [
                [_pdf_block("First paragraph")],
                [_pdf_block("Second paragraph"), _pdf_block("Third paragraph")],
            ]
        )
        chunks = chunk_block(document)
        assert [chunk.page for chunk in chunks] == [1, 2, 2]
        assert [chunk.id for chunk in chunks] == ["1-0", "2-0", "2-1"]

    def test_chunk_keeps_block_bbox(self) -> None:
        bbox = (5.0, 10.0, 200.0, 40.0)
        document = _document([[_pdf_block("text", bbox=bbox)]])
        chunks = chunk_block(document)
        assert chunks[0].bbox == bbox

    def test_image_blocks_skipped(self) -> None:
        document = _document(
            [
                [_pdf_block("only text"), _pdf_block("diagram", kind=BlockKind.IMAGE)],
                [_pdf_block("figure", kind=BlockKind.IMAGE)],
            ]
        )
        chunks = chunk_block(document)
        assert [chunk.text for chunk in chunks] == ["only text"]

    def test_empty_blocks_produce_no_chunks(self) -> None:
        document = _document(
            [[_pdf_block("   "), _pdf_block(""), _pdf_block("real text")]]
        )
        chunks = chunk_block(document)
        assert [chunk.text for chunk in chunks] == ["real text"]

    def test_oversized_block_split_at_sentence_boundaries(self) -> None:
        sentences = ["short sentence."] * ((MAX_CHUNK_CHARS // len("short sentence.")) + 3)
        long_text = " ".join(sentences)
        document = _document([[_pdf_block(long_text)]])
        chunks = chunk_block(document)
        assert len(chunks) > 1
        assert all(len(chunk.text) <= MAX_CHUNK_CHARS for chunk in chunks)
        assert all(chunk.page == 1 for chunk in chunks)
        # Sub-chunk ids get a `.sub` suffix; all share the parent block's bbox.
        assert all(chunk.id.startswith("1-0.") for chunk in chunks)
        assert all(chunk.bbox == (0.0, 0.0, 100.0, 10.0) for chunk in chunks)

    def test_kind_carried(self) -> None:
        document = _document([[_pdf_block("a table", kind=BlockKind.TABLE)]])
        assert chunk_block(document)[0].kind == "table"

    def test_chunks_carry_source(self) -> None:
        document = _document([[_pdf_block("text")]])
        assert chunk_block(document)[0].source == "pdf"


class TestTableRowMerge:
    def test_overlapping_cells_merge_into_one_row_chunk(self) -> None:
        document = _document(
            [
                [
                    _pdf_block("Model", kind=BlockKind.TABLE, bbox=(0.0, 10.0, 50.0, 20.0)),
                    _pdf_block("Latency (ms)", kind=BlockKind.TABLE, bbox=(51.0, 10.0, 120.0, 20.0)),
                ]
            ]
        )
        chunks = chunk_block(document)
        assert len(chunks) == 1
        assert chunks[0].kind == "table"
        assert chunks[0].text == "Model Latency (ms)"
        assert chunks[0].bbox == (0.0, 10.0, 120.0, 20.0)
        assert chunks[0].id == "1-0"

    def test_non_overlapping_cells_split_into_separate_rows(self) -> None:
        document = _document(
            [
                [
                    _pdf_block("row one cell", kind=BlockKind.TABLE, bbox=(0.0, 10.0, 50.0, 20.0)),
                    _pdf_block("row two cell", kind=BlockKind.TABLE, bbox=(0.0, 80.0, 50.0, 90.0)),
                ]
            ]
        )
        chunks = chunk_block(document)
        assert len(chunks) == 2
        assert [chunk.text for chunk in chunks] == ["row one cell", "row two cell"]
        assert [chunk.id for chunk in chunks] == ["1-0", "1-1"]

    def test_tiny_table_cell_still_joins_row(self) -> None:
        document = _document(
            [
                [
                    _pdf_block("x", kind=BlockKind.TABLE, bbox=(0.0, 10.0, 10.0, 20.0)),
                    _pdf_block("latency value", kind=BlockKind.TABLE, bbox=(11.0, 10.0, 80.0, 20.0)),
                ]
            ]
        )
        chunks = chunk_block(document)
        assert len(chunks) == 1
        assert chunks[0].text == "x latency value"


class TestListMerge:
    def test_consecutive_list_items_merge(self) -> None:
        document = _document(
            [
                [
                    _pdf_block("first item", kind=BlockKind.LIST, bbox=(0.0, 0.0, 100.0, 10.0)),
                    _pdf_block("second item", kind=BlockKind.LIST, bbox=(0.0, 12.0, 100.0, 22.0)),
                ]
            ]
        )
        chunks = chunk_block(document)
        assert len(chunks) == 1
        assert chunks[0].text == "first item second item"
        assert chunks[0].kind == "list"
        assert chunks[0].bbox == (0.0, 0.0, 100.0, 22.0)

    def test_list_merge_respects_chunk_cap(self) -> None:
        # Each item fits under the cap on its own; merging any pair would exceed it.
        big = "item " + "word " * 200  # 1005 chars
        assert len(big) <= MAX_CHUNK_CHARS
        assert 2 * len(big) + 1 > MAX_CHUNK_CHARS
        document = _document(
            [
                [
                    _pdf_block(big, kind=BlockKind.LIST),
                    _pdf_block(big, kind=BlockKind.LIST),
                    _pdf_block(big, kind=BlockKind.LIST),
                ]
            ]
        )
        chunks = chunk_block(document)
        assert [chunk.id for chunk in chunks] == ["1-0", "1-1", "1-2"]
        assert len({chunk.text for chunk in chunks}) == 1

    def test_list_does_not_merge_with_text_block(self) -> None:
        document = _document(
            [
                [
                    _pdf_block("first item", kind=BlockKind.LIST),
                    _pdf_block("a paragraph", kind=BlockKind.TEXT),
                ]
            ]
        )
        chunks = chunk_block(document)
        assert [chunk.text for chunk in chunks] == ["first item", "a paragraph"]
        assert [chunk.kind for chunk in chunks] == ["list", "text"]


class TestNoiseFilter:
    def test_tiny_text_block_dropped(self) -> None:
        document = _document([[_pdf_block("x")]])
        assert chunk_block(document) == []

    def test_tiny_text_between_real_blocks_dropped(self) -> None:
        document = _document(
            [[_pdf_block("real text"), _pdf_block("x"), _pdf_block("more text")]]
        )
        chunks = chunk_block(document)
        assert [chunk.text for chunk in chunks] == ["real text", "more text"]

    def test_table_rows_flush_before_text_block(self) -> None:
        document = _document(
            [
                [
                    _pdf_block("intro paragraph"),
                    _pdf_block("Model", kind=BlockKind.TABLE, bbox=(0.0, 10.0, 50.0, 20.0)),
                    _pdf_block("INT8", kind=BlockKind.TABLE, bbox=(51.0, 10.0, 80.0, 20.0)),
                    _pdf_block("outro paragraph"),
                ]
            ]
        )
        chunks = chunk_block(document)
        assert [chunk.text for chunk in chunks] == [
            "intro paragraph",
            "Model INT8",
            "outro paragraph",
        ]
        assert [chunk.kind for chunk in chunks] == ["text", "table", "text"]
        assert [chunk.id for chunk in chunks] == ["1-0", "1-1", "1-2"]