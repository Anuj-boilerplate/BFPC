"""Unit tests for the FAISS vector index (random vectors, no model)."""

from __future__ import annotations

import numpy as np
import pytest

from bfpc.index.chunker import Chunk
from bfpc.index.index import VectorIndex


def _chunk(text: str, page: int = 1) -> Chunk:
    return Chunk(id=f"c{page}", text=text, page=page, source="pdf")


def _unit_vector(rng: np.random.Generator, dim: int = 16) -> np.ndarray:
    vector = rng.normal(size=dim).astype(np.float32)
    return vector / np.linalg.norm(vector)


def _fill(index: VectorIndex, count: int, rng: np.random.Generator) -> None:
    chunks = [_chunk(f"chunk {i}", page=i + 1) for i in range(count)]
    vectors = np.stack([_unit_vector(rng) for _ in range(count)])
    index.add(chunks, vectors)


class TestVectorIndex:
    def test_returns_nearest_chunk_first(self) -> None:
        rng = np.random.default_rng(0)
        index = VectorIndex()
        _fill(index, 5, rng)
        query = _unit_vector(rng)
        hits = index.search(query, k=3)
        assert len(hits) == 3
        scores = [hit.score for hit in hits]
        assert scores == sorted(scores, reverse=True)
        assert all(isinstance(hit.score, float) for hit in hits)

    def test_exact_match_scores_near_one(self) -> None:
        rng = np.random.default_rng(1)
        index = VectorIndex()
        _fill(index, 5, rng)
        target = _unit_vector(rng)
        exact = np.stack([target])
        index.add([_chunk("exact", page=99)], exact)
        hits = index.search(target, k=1)
        assert hits[0].chunk.page == 99
        assert hits[0].score == pytest.approx(1.0, abs=1e-5)

    def test_search_empty_index_raises(self) -> None:
        index = VectorIndex()
        with pytest.raises(ValueError, match="empty"):
            index.search(_unit_vector(np.random.default_rng(0)), k=1)

    def test_k_clamped_to_index_size(self) -> None:
        rng = np.random.default_rng(2)
        index = VectorIndex()
        _fill(index, 3, rng)
        hits = index.search(_unit_vector(rng), k=10)
        assert len(hits) == 3

    def test_nonpositive_k_rejected(self) -> None:
        rng = np.random.default_rng(3)
        index = VectorIndex()
        _fill(index, 3, rng)
        with pytest.raises(ValueError, match="k must be"):
            index.search(_unit_vector(rng), k=0)

    def test_chunk_vector_count_mismatch_rejected(self) -> None:
        index = VectorIndex()
        chunks = [_chunk("a"), _chunk("b")]
        vectors = np.zeros((3, 16), dtype=np.float32)
        with pytest.raises(ValueError, match="got 2 chunks but 3 vectors"):
            index.add(chunks, vectors)

    def test_add_empty_is_noop(self) -> None:
        index = VectorIndex()
        index.add([], np.zeros((0, 16), dtype=np.float32))
        assert len(index) == 0

    def test_len_tracks_added_chunks(self) -> None:
        rng = np.random.default_rng(4)
        index = VectorIndex()
        _fill(index, 4, rng)
        assert len(index) == 4

    def test_equal_score_ties_prefer_text_over_heading(self) -> None:
        rng = np.random.default_rng(5)
        vector = _unit_vector(rng)
        index = VectorIndex()
        heading = Chunk(id="h1", text="a heading", page=1, source="pdf", kind="heading")
        body = Chunk(id="b1", text="body text", page=2, source="pdf", kind="text")
        # Identical vectors -> identical scores; inserted heading first so
        # FAISS would rank it first without the kind tie-break.
        index.add([heading, body], np.stack([vector, vector]))
        hits = index.search(vector, k=2)
        assert hits[0].chunk.kind == "text"
        assert hits[1].chunk.kind == "heading"
        assert hits[0].score == hits[1].score

    def test_tie_break_does_not_disturb_distinct_scores(self) -> None:
        rng = np.random.default_rng(6)
        index = VectorIndex()
        _fill(index, 5, rng)
        query = _unit_vector(rng)
        hits = index.search(query, k=5)
        scores = [hit.score for hit in hits]
        assert scores == sorted(scores, reverse=True)
