"""Deterministic offline generator: pipeline testing without LLM API calls.

Drop-in replacement for :class:`bfpc.context.gemini_generator.GeminiGenerator`
— the pipeline cannot tell them apart (that is the point of the
:class:`bfpc.context.base.Generator` contract).
"""

from __future__ import annotations

from collections.abc import Callable

from bfpc.context.base import Generator
from bfpc.context.builder import LLMContext
from bfpc.context.completeness import CompletenessReport, TrailReport
from bfpc.context.evidence import Claim, EvidenceResult


def _passing_report() -> CompletenessReport:
    return CompletenessReport(complete=True, reasons=[], uncovered_claims=[], unresolved_deps=[])


class MockGenerator(Generator):
    """Returns a fixed or derived :class:`TrailReport` without network.

    Wraps the historic :class:`EvidenceResult` API so existing tests that
    pass ``EvidenceResult`` or ``str`` continue to work — they are
    automatically wrapped into a :class:`TrailReport` with ``claims=[]``.
    """

    def __init__(
        self,
        reply: EvidenceResult | TrailReport | str | dict | Callable[[str, LLMContext], EvidenceResult | TrailReport | str | dict] | None = None,
    ) -> None:
        """:param reply: canned answer; a callable receives ``(query,
        context)`` and returns the result; ``None`` derives a reply from
        the inputs; a plain ``str`` becomes ``EvidenceResult(answer=str)``."""
        self._reply = reply
        #: Every ``(query, context)`` pair seen by :meth:`generate`.
        self.calls: list[tuple[str, LLMContext]] = []

    def generate(self, query: str, context: LLMContext) -> TrailReport:
        self.calls.append((query, context))
        if callable(self._reply):
            result = self._reply(query, context)  # type: ignore[call-arg]
            return self._coerce_to_trail(result, query, context)
        if self._reply is not None:
            return self._coerce_to_trail(self._reply, query, context)  # type: ignore[arg-type]
        cited = [source.source_id for source in context.sources]
        # Default mock: echo query as answer, role supporting for each source.
        nodes = [{"source_id": sid, "role": "supporting"} for sid in cited[:1]] if cited else []
        result = EvidenceResult(
            answer=f"[mock] {query} ({', '.join(cited) or 'no sources'})", nodes=nodes, relationships=[]  # type: ignore[arg-type]
        )
        return TrailReport(result=result, claims=[], report=_passing_report())

    @staticmethod
    def _coerce(
        value: EvidenceResult | str, query: str, context: LLMContext
    ) -> EvidenceResult:
        if isinstance(value, EvidenceResult):
            return value
        if isinstance(value, str):
            return EvidenceResult(answer=value, nodes=[], relationships=[])
        # Defensive: treat dict-like as well
        if isinstance(value, dict):
            # If dict carries claims, strip before validating EvidenceResult
            payload = dict(value)
            payload.pop("claims", None)
            payload.pop("report", None)
            payload.pop("result", None)
            if "answer" in payload or "nodes" in payload:
                return EvidenceResult.model_validate(payload)
            return EvidenceResult.model_validate(value)
        raise TypeError(f"unsupported mock reply type: {type(value)!r}")

    @staticmethod
    def _coerce_to_trail(value, query: str, context: LLMContext) -> TrailReport:  # type: ignore[no-untyped-def]
        if isinstance(value, TrailReport):
            return value
        if isinstance(value, EvidenceResult):
            return TrailReport(result=value, claims=[], report=_passing_report())
        if isinstance(value, str):
            result = EvidenceResult(answer=value, nodes=[], relationships=[])
            return TrailReport(result=result, claims=[], report=_passing_report())
        if isinstance(value, dict):
            # Support dicts that already look like TrailReport {result, claims, report}
            if "result" in value and isinstance(value["result"], EvidenceResult):
                claims_raw = value.get("claims", [])
                claims = [Claim.model_validate(c) if not isinstance(c, Claim) else c for c in claims_raw]
                report = value.get("report", _passing_report())
                if isinstance(report, dict):
                    report = CompletenessReport(**report)
                return TrailReport(result=value["result"], claims=claims, report=report)
            # Dict with claims + EvidenceResult fields
            payload = dict(value)
            raw_claims = payload.pop("claims", [])
            payload.pop("report", None)
            # If payload still contains TrailReport-like nesting, handle
            if "answer" in payload or "nodes" in payload or "relationships" in payload or "status" in payload:
                result = EvidenceResult.model_validate(payload)
                claims: list[Claim] = []
                if raw_claims:
                    for rc in raw_claims:
                        claims.append(Claim.model_validate(rc) if not isinstance(rc, Claim) else rc)
                return TrailReport(result=result, claims=claims, report=_passing_report())
            # Fallback: try as EvidenceResult
            return TrailReport(result=EvidenceResult.model_validate(value), claims=[], report=_passing_report())
        if isinstance(value, tuple) and len(value) == 2:
            # (EvidenceResult, list[Claim])
            res, claims_raw = value
            if isinstance(res, EvidenceResult):
                claims = [Claim.model_validate(c) if not isinstance(c, Claim) else c for c in claims_raw] if claims_raw else []
                return TrailReport(result=res, claims=claims, report=_passing_report())
        # Fall back to EvidenceResult coercion
        result = MockGenerator._coerce(value, query, context)
        return TrailReport(result=result, claims=[], report=_passing_report())
