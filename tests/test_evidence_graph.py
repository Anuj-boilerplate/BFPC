"""Phase 5 tests: evidence graph prototype over a fixed top-k context.

Proves the generator can build a *selective* graph — only the passages
necessary for the answer become nodes — without any iterative retrieval.
Gemini is exercised through ``httpx.MockTransport``.
"""

from __future__ import annotations

import json

import httpx
import pytest

from bfpc.context import (
    AnswerPipeline,
    ContextBuilder,
    EvidenceResult,
    GeneratorError,
    GeminiGenerator,
    MockGenerator,
)


_BASE = "https://example.test/v1beta"


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


def _context(top_k: int = 3):
    results = [_result(f"chunk_{i}") for i in range(1, top_k + 1)]
    return ContextBuilder().build(results)


def _gemini(handler: httpx.MockTransport.Handler) -> GeminiGenerator:
    return GeminiGenerator(
        base_url=_BASE,
        api_key="test-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        retry_delays=(),
    )


def _graph_reply(
    answer: str = "ok",
    nodes: list[dict] | None = None,
    relationships: list[dict] | None = None,
) -> dict:
    payload = {
        "answer": answer,
        "nodes": nodes or [],
        "relationships": relationships or [],
    }
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]}


class TestSingleRelevantPassage:
    def test_one_node_from_three_sources(self) -> None:
        nodes = [{"source_id": "SOURCE_2", "role": "supporting"}]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_graph_reply("single", nodes=nodes))

        result = _gemini(handler).generate("q", _context(3))
        assert [n.source_id for n in result.nodes] == ["SOURCE_2"]
        assert result.nodes[0].role == "supporting"
        assert result.relationships == []

    def test_node_must_come_from_context(self) -> None:
        # Selectivity is fine; hallucination is not — SOURCE_9 was never given.
        nodes = [{"source_id": "SOURCE_9", "role": "definition"}]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_graph_reply("bad", nodes=nodes))

        with pytest.raises(GeneratorError):
            _gemini(handler).generate("q", _context(3))


class TestMultipleRelevantPassages:
    def test_related_passages_form_connected_graph(self) -> None:
        nodes = [
            {"source_id": "SOURCE_1", "role": "context"},
            {"source_id": "SOURCE_3", "role": "supporting"},
            {"source_id": "SOURCE_5", "role": "conclusion"},
        ]
        relationships = [
            {"from": "SOURCE_1", "to": "SOURCE_3", "type": "explains"},
            {"from": "SOURCE_3", "to": "SOURCE_5", "type": "follows_from"},
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json=_graph_reply("multi", nodes=nodes, relationships=relationships)
            )

        result = _gemini(handler).generate("q", _context(5))
        assert len(result.nodes) == 3
        assert len(result.relationships) == 2
        assert {r.type for r in result.relationships} == {"explains", "follows_from"}

    def test_all_roles_reachable(self) -> None:
        roles = ["context", "supporting", "definition", "example", "conclusion"]
        nodes = [{"source_id": f"SOURCE_{i}", "role": role} for i, role in enumerate(roles, 1)]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_graph_reply("roles", nodes=nodes))

        result = _gemini(handler).generate("q", _context(5))
        assert [n.role for n in result.nodes] == roles


class TestDistractorPassages:
    def test_selective_graph_skips_distractors(self) -> None:
        # 5 supplied sources; only 2 are actually necessary.
        nodes = [
            {"source_id": "SOURCE_1", "role": "definition"},
            {"source_id": "SOURCE_4", "role": "supporting"},
        ]
        relationships = [{"from": "SOURCE_1", "to": "SOURCE_4", "type": "defines"}]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json=_graph_reply("selective", nodes=nodes, relationships=relationships)
            )

        result = _gemini(handler).generate("q", _context(5))
        selected = {n.source_id for n in result.nodes}
        assert selected == {"SOURCE_1", "SOURCE_4"}
        assert len(selected) < len(result_nodes_context := _context(5).sources)

    def test_relationship_to_unselected_source_is_invalid_shape(self) -> None:
        # SOURCE_2 exists in the context but was NOT selected as a node;
        # relationship endpoints must reference existing nodes only.
        nodes = [{"source_id": "SOURCE_1", "role": "context"}]
        relationships = [{"from": "SOURCE_1", "to": "SOURCE_2", "type": "supports"}]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json=_graph_reply("leaky", nodes=nodes, relationships=relationships)
            )

        with pytest.raises(GeneratorError, match="invalid evidence shape"):
            _gemini(handler).generate("q", _context(3))


class TestGraphViaPipeline:
    def test_mock_pipeline_returns_selective_graph(self) -> None:
        class FakeRetriever:
            def search(self, query: str, top_k: int) -> dict:
                return {
                    "query": query,
                    "top_k": top_k,
                    "hits": [_result(f"chunk_{i}") for i in range(1, 6)],
                }

        structured = EvidenceResult(
            answer="two sources suffice",
            nodes=[
                {"source_id": "SOURCE_1", "role": "context"},
                {"source_id": "SOURCE_3", "role": "example"},
            ],
            relationships=[{"from": "SOURCE_1", "to": "SOURCE_3", "type": "supports"}],
        )
        pipeline = AnswerPipeline(
            retriever=FakeRetriever(),
            generator=MockGenerator(reply=structured),
        )
        result = pipeline.answer("q?")
        assert len(result.nodes) == 2

    def test_gemini_graph_flows_through_pipeline(self) -> None:
        class FakeRetriever:
            def __init__(self) -> None:
                self.calls = 0

            def search(self, query: str, top_k: int) -> dict:
                self.calls += 1
                return {
                    "query": query,
                    "top_k": top_k,
                    "hits": [_result(f"chunk_{i}") for i in range(1, 6)],
                }

        retriever = FakeRetriever()
        nodes = [
            {"source_id": "SOURCE_2", "role": "supporting"},
            {"source_id": "SOURCE_5", "role": "conclusion"},
        ]
        gemini = _gemini(
            lambda request: httpx.Response(
                200,
                json=_graph_reply(
                    "pipeline graph",
                    nodes=nodes,
                    relationships=[{"from": "SOURCE_2", "to": "SOURCE_5", "type": "supports"}],
                ),
            )
        )
        pipeline = AnswerPipeline(retriever=retriever, generator=gemini)
        result = pipeline.answer("why?")
        assert result.answer == "pipeline graph"
        assert len(result.relationships) == 1
        # Exactly one retrieval pass — no iterative expansion.
        assert retriever.calls == 1


class TestMalformedGraphs:
    @pytest.mark.parametrize(
        ("nodes", "relationships"),
        [
            # duplicate node id
            (
                [
                    {"source_id": "SOURCE_1", "role": "context"},
                    {"source_id": "SOURCE_1", "role": "supporting"},
                ],
                [],
            ),
            # self-referential edge
            (
                [{"source_id": "SOURCE_1", "role": "context"}],
                [{"from": "SOURCE_1", "to": "SOURCE_1", "type": "supports"}],
            ),
            # unknown role enum
            (
                [{"source_id": "SOURCE_1", "role": "contradicting"}],
                [],
            ),
            # unknown relationship type enum
            (
                [
                    {"source_id": "SOURCE_1", "role": "context"},
                    {"source_id": "SOURCE_2", "role": "supporting"},
                ],
                [{"from": "SOURCE_1", "to": "SOURCE_2", "type": "elaborates"}],
            ),
        ],
    )
    def test_malformed_structured_output_raises_generator_error(
        self, nodes: list[dict], relationships: list[dict]
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json=_graph_reply("malformed", nodes=nodes, relationships=relationships)
            )

        with pytest.raises(GeneratorError):
            _gemini(handler).generate("q", _context(3))
