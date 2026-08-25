"""Phase 9 tests: deterministic completeness checker (4 rules).

Covers the TrailReport wrapper and the pure check() function.
"""

from __future__ import annotations

import pytest

from bfpc.context import Claim, ContextBuilder, EvidenceResult
from bfpc.context.completeness import CompletenessReport, TrailReport, check


def _result(chunk_id: str, text: str, **overrides) -> dict:
    base: dict = {
        "chunk_id": chunk_id,
        "text": text,
        "page": 1,
        "kind": "text",
        "score": 0.5,
        "bbox": None,
        "snippet": None,
        "rects": None,
    }
    base.update(overrides)
    return base


def _ctx(*texts: str, top_k: int | None = None) -> "LLMContext":
    results = [_result(f"chunk_{i}", t) for i, t in enumerate(texts, 1)]
    builder = ContextBuilder(top_k=top_k) if top_k is not None else ContextBuilder()
    return builder.build(results)


class TestCompletenessChecker:
    def test_happy_path_all_rules_pass(self) -> None:
        ctx = _ctx("INT8 latency is 18.48 ms", "other passage")
        result = EvidenceResult(
            answer="INT8 latency is 18.48 ms",
            status="SUFFICIENT",
            nodes=[{"source_id": "SOURCE_1", "role": "supporting"}],  # type: ignore[arg-type]
            relationships=[],
        )
        claims = [
            Claim(id="C1", text="INT8 latency is 18.48 ms", required=True, evidence_ids=["SOURCE_1"], depends_on=[])
        ]
        report = check(result, claims, ctx, budget=10)
        assert report.complete is True
        assert report.reasons == []
        assert report.uncovered_claims == []
        assert report.unresolved_deps == []

    def test_rule1_unknown_answer(self) -> None:
        ctx = _ctx("some unrelated passage")
        result = EvidenceResult(answer="I don't know", status="SUFFICIENT", nodes=[], relationships=[])
        report = check(result, [], ctx, budget=10)
        assert report.complete is False
        assert any("Rule 1" in r for r in report.reasons)

    def test_rule1_no_supporting_node(self) -> None:
        ctx = _ctx("some passage")
        result = EvidenceResult(
            answer="some passage answer",
            status="SUFFICIENT",
            nodes=[{"source_id": "SOURCE_1", "role": "context"}],  # type: ignore[arg-type]
            relationships=[],
        )
        report = check(result, [], ctx, budget=10)
        assert report.complete is False
        assert any("Rule 1" in r for r in report.reasons)

    def test_rule1_no_jaccard_overlap(self) -> None:
        ctx = _ctx("completely different chunk content")
        result = EvidenceResult(
            answer="unrelated answer with no overlap",
            status="SUFFICIENT",
            nodes=[{"source_id": "SOURCE_1", "role": "supporting"}],  # type: ignore[arg-type]
            relationships=[],
        )
        report = check(result, [], ctx, budget=10)
        assert report.complete is False
        assert any("Rule 1" in r for r in report.reasons)

    def test_rule2_required_claim_not_backed(self) -> None:
        ctx = _ctx("text of chunk_1")
        result = EvidenceResult(
            answer="text of chunk_1",
            status="SUFFICIENT",
            nodes=[{"source_id": "SOURCE_1", "role": "supporting"}],  # type: ignore[arg-type]
            relationships=[],
        )
        claims = [
            Claim(id="C1", text="claim", required=True, evidence_ids=["SOURCE_99"], depends_on=[]),
        ]
        report = check(result, claims, ctx, budget=10)
        assert report.complete is False
        assert "C1" in report.uncovered_claims
        assert any("Rule 2" in r for r in report.reasons)

    def test_rule2_required_false_no_evidence_still_complete(self) -> None:
        ctx = _ctx("text of chunk_1")
        result = EvidenceResult(
            answer="text of chunk_1",
            status="SUFFICIENT",
            nodes=[{"source_id": "SOURCE_1", "role": "supporting"}],  # type: ignore[arg-type]
            relationships=[],
        )
        claims = [
            Claim(id="C1", text="optional", required=False, evidence_ids=[], depends_on=[]),
        ]
        report = check(result, claims, ctx, budget=10)
        assert report.complete is True
        assert report.uncovered_claims == []

    def test_rule2_multiple_claims_one_uncovered(self) -> None:
        ctx = _ctx("text of chunk_1", "text of chunk_2")
        result = EvidenceResult(
            answer="text of chunk_1",
            status="SUFFICIENT",
            nodes=[
                {"source_id": "SOURCE_1", "role": "supporting"},  # type: ignore[arg-type]
                {"source_id": "SOURCE_2", "role": "context"},  # type: ignore[arg-type]
            ],
            relationships=[],
        )
        claims = [
            Claim(id="C1", text="c1", required=True, evidence_ids=["SOURCE_1"], depends_on=[]),
            Claim(id="C2", text="c2", required=True, evidence_ids=["SOURCE_2"], depends_on=[]),  # SOURCE_2 is not supporting
        ]
        report = check(result, claims, ctx, budget=10)
        assert report.complete is False
        assert report.uncovered_claims == ["C2"]

    def test_rule3_dangling_dependency(self) -> None:
        ctx = _ctx("text")
        result = EvidenceResult(
            answer="text",
            status="SUFFICIENT",
            nodes=[{"source_id": "SOURCE_1", "role": "supporting"}],  # type: ignore[arg-type]
            relationships=[],
        )
        claims = [
            Claim(id="C2", text="b", required=True, evidence_ids=["SOURCE_1"], depends_on=["C3"]),
        ]
        report = check(result, claims, ctx, budget=10)
        assert report.complete is False
        assert "C3" in report.unresolved_deps
        assert any("Rule 3" in r for r in report.reasons)

    def test_rule3_chain_missing(self) -> None:
        ctx = _ctx("text")
        result = EvidenceResult(
            answer="text",
            status="SUFFICIENT",
            nodes=[{"source_id": "SOURCE_1", "role": "supporting"}],  # type: ignore[arg-type]
            relationships=[],
        )
        claims = [
            Claim(id="C1", text="a", required=True, evidence_ids=["SOURCE_1"], depends_on=["C2"]),
            Claim(id="C2", text="b", required=True, evidence_ids=["SOURCE_1"], depends_on=["C3"]),
        ]
        report = check(result, claims, ctx, budget=10)
        assert report.complete is False
        assert "C3" in report.unresolved_deps

    def test_rule3_no_dangling_when_all_exist(self) -> None:
        ctx = _ctx("text")
        result = EvidenceResult(
            answer="text",
            status="SUFFICIENT",
            nodes=[{"source_id": "SOURCE_1", "role": "supporting"}],  # type: ignore[arg-type]
            relationships=[],
        )
        claims = [
            Claim(id="C1", text="a", required=True, evidence_ids=["SOURCE_1"], depends_on=[]),
            Claim(id="C2", text="b", required=True, evidence_ids=["SOURCE_1"], depends_on=["C1"]),
        ]
        report = check(result, claims, ctx, budget=10)
        assert report.complete is True
        assert report.unresolved_deps == []

    def test_rule4_exceeds_budget(self) -> None:
        # Build context with 11 sources
        texts = [f"chunk {i} text" for i in range(11)]
        ctx = _ctx(*texts, top_k=11)
        assert len(ctx.sources) == 11
        result = EvidenceResult(
            answer="chunk 0 text",
            status="SUFFICIENT",
            nodes=[{"source_id": "SOURCE_1", "role": "supporting"}],  # type: ignore[arg-type]
            relationships=[],
        )
        report = check(result, [], ctx, budget=10)
        assert report.complete is False
        assert any("Rule 4" in r for r in report.reasons)

    def test_rule4_within_budget(self) -> None:
        ctx = _ctx("a", "b", "c")
        result = EvidenceResult(
            answer="a",
            status="SUFFICIENT",
            nodes=[{"source_id": "SOURCE_1", "role": "supporting"}],  # type: ignore[arg-type]
            relationships=[],
        )
        report = check(result, [], ctx, budget=10)
        assert report.complete is True

    def test_empty_claims_with_valid_answer(self) -> None:
        ctx = _ctx("answer text")
        result = EvidenceResult(
            answer="answer text",
            status="SUFFICIENT",
            nodes=[{"source_id": "SOURCE_1", "role": "supporting"}],  # type: ignore[arg-type]
            relationships=[],
        )
        report = check(result, [], ctx, budget=10)
        assert report.complete is True

    def test_all_four_rules_fail(self) -> None:
        # Use unknown answer (Rule1), uncovered claim (Rule2), dangling (Rule3), budget exceed (Rule4)
        texts = [f"chunk {i}" for i in range(11)]
        ctx = _ctx(*texts, top_k=11)
        result = EvidenceResult(answer="I don't know", status="SUFFICIENT", nodes=[], relationships=[])
        claims = [Claim(id="C1", text="x", required=True, evidence_ids=[], depends_on=["C99"])]
        report = check(result, claims, ctx, budget=10)
        assert report.complete is False
        assert len(report.reasons) == 4
        assert "C1" in report.uncovered_claims
        assert "C99" in report.unresolved_deps

    def test_check_is_pure_no_mutation(self) -> None:
        ctx = _ctx("text")
        result = EvidenceResult(answer="text", status="SUFFICIENT", nodes=[{"source_id": "SOURCE_1", "role": "supporting"}], relationships=[])  # type: ignore[arg-type]
        claims = [Claim(id="C1", text="t", required=True, evidence_ids=["SOURCE_1"], depends_on=[])]
        report1 = check(result, claims, ctx, budget=10)
        report2 = check(result, claims, ctx, budget=10)
        assert report1 == report2

    def test_definition_role_counts_as_supporting_for_rule1(self) -> None:
        ctx = _ctx("definition text")
        result = EvidenceResult(
            answer="definition text",
            status="SUFFICIENT",
            nodes=[{"source_id": "SOURCE_1", "role": "definition"}],  # type: ignore[arg-type]
            relationships=[],
        )
        report = check(result, [], ctx, budget=10)
        assert report.complete is True

    def test_trail_report_wrapper(self) -> None:
        ctx = _ctx("text")
        result = EvidenceResult(answer="text", status="SUFFICIENT", nodes=[{"source_id": "SOURCE_1", "role": "supporting"}], relationships=[])  # type: ignore[arg-type]
        claims = [Claim(id="C1", text="t", required=True, evidence_ids=["SOURCE_1"], depends_on=[])]
        report = check(result, claims, ctx, budget=10)
        trail = TrailReport(result=result, claims=claims, report=report)
        assert trail.result is result
        assert trail.claims == claims
        assert trail.report == report
        # Delegation
        assert trail.answer == result.answer
        assert trail.status == result.status
