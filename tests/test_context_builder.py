"""Unit tests for the Phase 1 context builder (bfpc.context).

Covers the Phase 1 acceptance criteria: top-5 selection, retrieval-order
preservation, SOURCE_N mapping, duplicate removal, exclusion of internal
fields from the LLM payload, and access to the original results.
"""

from __future__ import annotations

import dataclasses

import pytest

from bfpc.context import (
    DEFAULT_TOP_K,
    ContextBuilder,
    LLMContext,
    MalformedRetrievalResult,
    Source,
)


def _result(chunk_id: str, **overrides) -> dict:
    """One Phase 0 hit in the contract §5.2 shape."""
    result: dict = {
        "chunk_id": chunk_id,
        "text": f"text of {chunk_id}",
        "page": 43,
        "kind": "text",
        "score": 0.73,
        "bbox": [45.0, 520.0, 400.0, 545.0],
        "snippet": f"best sentence of {chunk_id}",
        "rects": [[45.0, 523.5, 60.1, 535.8]],
    }
    result.update(overrides)
    return result


@pytest.fixture()
def eight_results() -> list[dict]:
    chunk_ids = [
        "chunk_381",
        "chunk_419",
        "chunk_271",
        "chunk_5",
        "chunk_9",
        "chunk_77",
        "chunk_1000",
        "chunk_2",
    ]
    return [_result(chunk_id) for chunk_id in chunk_ids]


class TestTopKSelection:
    def test_default_top_k_is_five(self) -> None:
        assert DEFAULT_TOP_K == 5

    def test_only_top_five_go_forward(self, eight_results: list[dict]) -> None:
        context = ContextBuilder().build(eight_results)
        assert len(context.sources) == 5

    def test_fewer_results_than_top_k_keeps_all(self) -> None:
        context = ContextBuilder().build([_result("chunk_381")])
        assert len(context.sources) == 1

    def test_empty_input_yields_empty_context(self) -> None:
        context = ContextBuilder().build([])
        assert context == LLMContext(sources=(), originals={})

    def test_custom_top_k_is_respected(self) -> None:
        results = [_result(f"chunk_{i}") for i in range(10)]
        context = ContextBuilder(top_k=2).build(results)
        assert [source.chunk_id for source in context.sources] == ["chunk_0", "chunk_1"]


class TestOrderAndMapping:
    def test_retrieval_order_is_preserved(self, eight_results: list[dict]) -> None:
        context = ContextBuilder().build(eight_results)
        assert [source.chunk_id for source in context.sources] == [
            "chunk_381",
            "chunk_419",
            "chunk_271",
            "chunk_5",
            "chunk_9",
        ]

    def test_source_ids_are_sequential_from_one(self, eight_results: list[dict]) -> None:
        context = ContextBuilder().build(eight_results)
        assert [source.source_id for source in context.sources] == [
            f"SOURCE_{i}" for i in range(1, 6)
        ]

    def test_spec_example_mapping(self) -> None:
        results = [_result(chunk_id) for chunk_id in ("chunk_381", "chunk_419", "chunk_271")]
        context = ContextBuilder().build(results)
        assert [(s.source_id, s.chunk_id) for s in context.sources] == [
            ("SOURCE_1", "chunk_381"),
            ("SOURCE_2", "chunk_419"),
            ("SOURCE_3", "chunk_271"),
        ]


class TestDeduplication:
    def test_duplicate_chunk_id_removed_first_occurrence_wins(self) -> None:
        first = _result("chunk_381", score=0.99, text="first copy")
        second = _result("chunk_381", score=0.10, text="second copy")
        third = _result("chunk_419")
        context = ContextBuilder().build([first, second, third])
        assert [source.chunk_id for source in context.sources] == ["chunk_381", "chunk_419"]
        assert context.sources[0].text == "first copy"
        assert context.original("SOURCE_1") is not None
        assert context.original("SOURCE_1")["score"] == 0.99

    def test_duplicate_does_not_consume_a_selection_slot(self, eight_results: list[dict]) -> None:
        duplicated = [eight_results[0], *eight_results]
        context = ContextBuilder().build(duplicated)
        # Dedup happens before selection, so the collapsed duplicate lets a
        # fifth distinct chunk (chunk_9) into the context.
        assert [source.chunk_id for source in context.sources] == [
            "chunk_381",
            "chunk_419",
            "chunk_271",
            "chunk_5",
            "chunk_9",
        ]


class TestProjection:
    def test_sources_carry_exactly_the_llm_fields(self, eight_results: list[dict]) -> None:
        context = ContextBuilder().build(eight_results)
        field_names = {field.name for field in dataclasses.fields(Source)}
        assert field_names == {"source_id", "chunk_id", "page", "kind", "text"}

    def test_internal_fields_are_absent_from_sources(self, eight_results: list[dict]) -> None:
        context = ContextBuilder().build(eight_results)
        for source in context.sources:
            for internal in ("score", "bbox", "snippet", "rects"):
                assert not hasattr(source, internal)

    def test_source_values_match_their_result(self, eight_results: list[dict]) -> None:
        context = ContextBuilder().build(eight_results)
        source = context.sources[1]
        original = eight_results[1]
        assert (source.chunk_id, source.page, source.kind, source.text) == (
            original["chunk_id"],
            original["page"],
            original["kind"],
            original["text"],
        )


class TestOriginalAccess:
    def test_original_result_remains_accessible(self, eight_results: list[dict]) -> None:
        context = ContextBuilder().build(eight_results)
        original = context.original("SOURCE_2")
        assert original is not None
        assert original["chunk_id"] == "chunk_419"
        assert original["score"] == 0.73
        assert original["bbox"] == [45.0, 520.0, 400.0, 545.0]
        assert original["snippet"] == "best sentence of chunk_419"
        assert original["rects"] == [[45.0, 523.5, 60.1, 535.8]]

    def test_unknown_source_id_returns_none(self) -> None:
        context = ContextBuilder().build([_result("chunk_381")])
        assert context.original("SOURCE_99") is None

    def test_originals_cover_exactly_every_source(self, eight_results: list[dict]) -> None:
        context = ContextBuilder().build(eight_results)
        assert set(context.originals) == {source.source_id for source in context.sources}


class TestValidation:
    def test_missing_required_field_raises(self) -> None:
        broken = _result("chunk_381")
        del broken["page"]
        with pytest.raises(MalformedRetrievalResult, match="page"):
            ContextBuilder().build([broken])

    def test_blank_required_field_raises(self) -> None:
        with pytest.raises(MalformedRetrievalResult, match="blank"):
            ContextBuilder().build([_result("chunk_381", text="   ")])

    def test_non_mapping_result_raises_clearly(self) -> None:
        with pytest.raises(MalformedRetrievalResult, match="missing required field"):
            ContextBuilder().build([None])  # type: ignore[list-item]

    def test_non_positive_top_k_raises(self) -> None:
        with pytest.raises(ValueError, match="top_k"):
            ContextBuilder(top_k=0)
