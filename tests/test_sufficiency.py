"""Phase 6 tests: evidence sufficiency (SUFFICIENT / INSUFFICIENT).

The LLM must recognize when the top-k context is not enough and say what
is missing — and the pipeline must STOP there: no retrieval expansion.
"""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError

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
    result: dict = {
        "chunk_id": chunk_id,
        "text": f"text of {chunk_id} enough missing definition",
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


def _reply(payload: dict) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]}


class TestEvidenceResultStatus:
    def test_status_defaults_to_sufficient(self) -> None:
        result = EvidenceResult(answer="done")
        assert result.status == "SUFFICIENT"
        assert result.missing is None

    def test_insufficient_requires_missing(self) -> None:
        with pytest.raises(ValidationError, match="'missing' description"):
            EvidenceResult(answer="can't answer", status="INSUFFICIENT")

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_insufficient_blank_missing_rejected(self, blank: str) -> None:
        with pytest.raises(ValidationError):
            EvidenceResult(answer="x", status="INSUFFICIENT", missing=blank)

    def test_sufficient_must_not_carry_missing(self) -> None:
        with pytest.raises(ValidationError, match="must not carry"):
            EvidenceResult(
                answer="full answer", status="SUFFICIENT", missing="nothing really"
            )

    def test_valid_insufficient_result(self) -> None:
        result = EvidenceResult(
            answer="partial",
            status="INSUFFICIENT",
            missing="the definition of adaptive congestion control",
        )
        assert result.status == "INSUFFICIENT"
        assert result.missing == "the definition of adaptive congestion control"

    def test_invalid_status_enum_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceResult(answer="x", status="MAYBE")  # type: ignore[arg-type]

    def test_round_trip_preserves_status_and_missing(self) -> None:
        result = EvidenceResult(
            answer="x", status="INSUFFICIENT", missing="a supporting benchmark"
        )
        restored = EvidenceResult.model_validate(result.model_dump())
        assert restored == result


class TestGeminiSufficiency:
    def test_complete_top_five_reports_sufficient(self) -> None:
        payload = {
            "answer": "INT8 static quantization cuts latency to 18.48 ms.",
            "status": "SUFFICIENT",
            "nodes": [{"source_id": "SOURCE_1", "role": "supporting"}],
            "relationships": [],
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_reply(payload))

        result = _gemini(handler).generate("q", _context(5))
        assert result.status == "SUFFICIENT"
        assert result.missing is None

    def test_missing_definition_reports_insufficient(self) -> None:
        payload = {
            "answer": "Cannot fully answer.",
            "status": "INSUFFICIENT",
            "missing": "the definition of adaptive congestion control",
            "nodes": [],
            "relationships": [],
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_reply(payload))

        result = _gemini(handler).generate("q", _context(5))
        assert result.status == "INSUFFICIENT"
        assert result.missing == "the definition of adaptive congestion control"

    def test_missing_supporting_evidence_with_partial_graph(self) -> None:
        payload = {
            "answer": "Partial picture only.",
            "status": "INSUFFICIENT",
            "missing": "a latency measurement for multi-core CPU server nodes",
            "nodes": [{"source_id": "SOURCE_1", "role": "context"}],
            "relationships": [],
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_reply(payload))

        result = _gemini(handler).generate("q", _context(3))
        assert result.status == "INSUFFICIENT"
        # partial graph is still allowed alongside the missing description
        assert len(result.nodes) == 1

    def test_distractor_heavy_context_still_gets_correct_status(self) -> None:
        payload = {
            "answer": "The supplied passages are off-topic.",
            "status": "INSUFFICIENT",
            "missing": "any passage about pricing models",
            "nodes": [],
            "relationships": [],
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_reply(payload))

        result = _gemini(handler).generate("pricing?", _context(5))
        assert result.status == "INSUFFICIENT"

    def test_llm_insufficient_without_missing_is_shape_error(self) -> None:
        payload = {
            "answer": "not enough",
            "status": "INSUFFICIENT",
            "nodes": [],
            "relationships": [],
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_reply(payload))

        with pytest.raises(GeneratorError, match="invalid evidence shape"):
            _gemini(handler).generate("q", _context(2))

    def test_llm_sufficient_with_missing_is_shape_error(self) -> None:
        payload = {
            "answer": "fine",
            "status": "SUFFICIENT",
            "missing": "stray field",
            "nodes": [],
            "relationships": [],
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_reply(payload))

        with pytest.raises(GeneratorError, match="invalid evidence shape"):
            _gemini(handler).generate("q", _context(2))


class TestMockSufficiency:
    def test_default_mock_is_sufficient(self) -> None:
        result = MockGenerator().generate("q", _context())
        assert result.status == "SUFFICIENT"
        assert result.missing is None

    def test_canned_dict_carries_insufficient(self) -> None:
        canned = {
            "answer": "cannot answer",
            "status": "INSUFFICIENT",
            "missing": "the missing definition",
        }
        result = MockGenerator(reply=canned).generate("q", _context())
        assert result.status == "INSUFFICIENT"
        assert result.missing == "the missing definition"


class _CountingRetriever:
    """Records every retrieval pass; used to prove the pipeline stops."""

    def __init__(self, hits: list[dict]) -> None:
        self._hits = hits
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, top_k: int) -> dict:
        self.calls.append((query, top_k))
        return {"query": query, "top_k": top_k, "hits": self._hits}


class TestPipelineBoundedRetrieval:
    def test_insufficient_triggers_only_one_targeted_pass(self) -> None:
        # Phase 7: the missing description drives exactly ONE extra
        # retrieval. The counting retriever always returns the same hits,
        # so the targeted pass finds nothing new and the process ends with
        # the round-1 verdict — still a single generation.
        canned = EvidenceResult(
            answer="I'm missing X text of chunk_1",
            status="INSUFFICIENT",
            missing="the definition of adaptive congestion control",
        )
        retriever = _CountingRetriever([_result(f"chunk_{i}") for i in range(1, 6)])
        generator = MockGenerator(reply=canned)
        pipeline = AnswerPipeline(retriever=retriever, generator=generator)
        result = pipeline.answer("how does adaptive congestion control work?")
        # Phase 9: pipeline returns TrailReport wrapping canned
        assert result.result is canned or result.answer == canned.answer
        assert result.status == "INSUFFICIENT"
        assert retriever.calls == [
            ("how does adaptive congestion control work?", 5),
            ("the definition of adaptive congestion control", 5),
        ]
        assert len(generator.calls) == 1

    def test_sufficient_answer_also_single_pass(self) -> None:
        # Provide supporting evidence so Rule 1 passes
        sufficient = EvidenceResult(
            answer="enough text of chunk_1",
            status="SUFFICIENT",
            nodes=[{"source_id": "SOURCE_1", "role": "supporting"}],  # type: ignore[arg-type]
            relationships=[],
        )
        retriever = _CountingRetriever([_result("chunk_1")])
        pipeline = AnswerPipeline(
            retriever=retriever, generator=MockGenerator(reply=sufficient)
        )
        result = pipeline.answer("q?")
        assert result.status == "SUFFICIENT"
        assert result.report.complete is True
        assert len(retriever.calls) == 1
