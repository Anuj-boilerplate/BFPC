"""Phases 2/7/8 pipeline: Query -> Retriever -> ContextBuilder -> Generator.

Implements the bounded evidence-construction loop:

    Query -> initial top-k retrieval -> Generator
        SUFFICIENT   -> final evidence graph
        INSUFFICIENT -> ONE targeted retrieval whose query is the
                        generator's ``missing`` description, merged into
                        an expanded context (deduplicated by ``chunk_id``,
                        capped at ``max_evidence`` total sources), then the
                        generator runs once more for the final graph.

End states after expansion — no further rounds, ever:
* second generation still INSUFFICIENT -> that explicit result is returned;
* targeted retrieval found nothing new -> the round-1 INSUFFICIENT result;
* targeted retrieval raised           -> the round-1 INSUFFICIENT result.

The LLM never touches the retriever. Orchestration, deduplication and
budgets live here; the generator only ever sees ``(query, LLMContext)``
and decides which sources matter and how they relate.
"""

from __future__ import annotations

from typing import Protocol

from bfpc.context.base import Generator
from bfpc.context.builder import DEFAULT_TOP_K, ContextBuilder, LLMContext
from bfpc.context.completeness import CompletenessReport, TrailReport, check
from bfpc.context.evidence import EvidenceResult

#: Hard cap on total distinct sources across initial + targeted evidence.
DEFAULT_MAX_EVIDENCE = 10


class Retriever(Protocol):
    """Structural type for anything shaped like ``IndexService.search``."""

    def search(self, query: str, top_k: int) -> dict: ...


class AnswerPipeline:
    """End-to-end bounded evidence-construction loop over one document."""

    def __init__(
        self,
        retriever: Retriever,
        generator: Generator,
        builder: ContextBuilder | None = None,
        max_evidence: int = DEFAULT_MAX_EVIDENCE,
    ) -> None:
        """:param retriever: anything with ``IndexService.search``'s shape.
        :param generator: the Phase 2 boundary; never given retrieval access.
        :param builder: context builder fixing the initial top-k size.
        :param max_evidence: total distinct sources allowed across both
            retrieval passes (initial k + targeted top-up)."""
        if max_evidence < 1:
            raise ValueError(f"max_evidence must be >= 1, got {max_evidence}")
        self._retriever = retriever
        self._generator = generator
        self._builder = builder if builder is not None else ContextBuilder()
        self._max_evidence = max_evidence
        self._last_context: LLMContext | None = None
        # Alias for spec compatibility
        self._context_last: LLMContext | None = None

    def answer(self, query: str) -> TrailReport:
        """Run the loop; always returns a terminal :class:`TrailReport`.

        The LLM's sufficiency verdict is necessary but not sufficient — the
        deterministic checker (4 rules) has the final word.
        """
        results = self._retriever.search(query, self._builder.top_k)
        initial_hits = results.get("hits", [])
        context: LLMContext = self._builder.build(initial_hits)
        self._last_context = context
        self._context_last = context
        trail: TrailReport = self._coerce_trail(self._generator.generate(query, context))
        final_context = context

        # Phase 7/8 expansion if generator says INSUFFICIENT
        if trail.result.status == "INSUFFICIENT":
            # Try exactly one targeted retrieval
            remaining_budget = self._max_evidence - len(context.sources)
            if remaining_budget > 0:
                target_k = min(self._builder.top_k, remaining_budget)
                missing_query = (trail.result.missing or "").strip() or query
                try:
                    targeted_results = self._retriever.search(missing_query, target_k)
                    targeted_hits = targeted_results.get("hits", [])
                except Exception:
                    targeted_hits = []
                else:
                    known_ids = {source.chunk_id for source in context.sources}
                    has_new = any(
                        hit.get("chunk_id") not in known_ids for hit in targeted_hits
                    )
                    if has_new:
                        expanded_context = ContextBuilder(top_k=self._max_evidence).build(
                            [*initial_hits, *targeted_hits]
                        )
                        new_trail = self._coerce_trail(
                            self._generator.generate(query, expanded_context)
                        )
                        trail = new_trail
                        final_context = expanded_context
                        self._last_context = expanded_context
                        self._context_last = expanded_context
                    # else keep original trail/context

        # Phase 9 deterministic checker (uses final context actually sent to LLM)
        report = check(trail.result, trail.claims, final_context, self._max_evidence)
        if not report.complete:
            # Override to INSUFFICIENT with checker reasons as missing
            overridden = trail.result.model_copy(
                update={"status": "INSUFFICIENT", "missing": "; ".join(report.reasons)}
            )
            return TrailReport(result=overridden, claims=trail.claims, report=report)
        # Attach the real report (even when complete)
        return TrailReport(result=trail.result, claims=trail.claims, report=report)

    def _coerce_trail(self, value) -> TrailReport:  # type: ignore[no-untyped-def]
        """Accept both legacy EvidenceResult and new TrailReport."""
        # Avoid circular import at runtime
        from bfpc.context.completeness import TrailReport as _TrailReport

        if isinstance(value, _TrailReport):
            return value
        if isinstance(value, EvidenceResult):
            # Wrap legacy result with empty claims and a placeholder report
            placeholder = CompletenessReport(
                complete=True, reasons=[], uncovered_claims=[], unresolved_deps=[]
            )
            return TrailReport(result=value, claims=[], report=placeholder)
        # Dict-like or other: try to coerce via EvidenceResult
        if isinstance(value, dict):
            # Might be a TrailReport dict
            if "result" in value:
                # Already handled above but keep for safety
                result = value.get("result")
                if isinstance(result, EvidenceResult):
                    claims = value.get("claims", [])
                    report = value.get("report")
                    if report is None:
                        report = CompletenessReport(complete=True, reasons=[], uncovered_claims=[], unresolved_deps=[])
                    return TrailReport(result=result, claims=claims, report=report)
            # Assume EvidenceResult payload
            result = EvidenceResult.model_validate(value)
            return TrailReport(
                result=result,
                claims=[],
                report=CompletenessReport(complete=True, reasons=[], uncovered_claims=[], unresolved_deps=[]),
            )
        raise TypeError(f"generator returned unsupported type {type(value)!r}")

    # -- internals ---------------------------------------------------------

    def _expand(
        self,
        query: str,
        initial_hits: list,
        context: LLMContext,
        trail,  # TrailReport | EvidenceResult (legacy)
    ) -> TrailReport:
        """One targeted retrieval pass driven by the reported gap.

        Kept for backward compat with older callers / tests that invoke
        ``_expand`` directly. New ``answer()`` inlines this logic and
        tracks the expanded context explicitly.

        Returns the original trail if no expansion is possible or needed.
        """
        # Support legacy callers that passed EvidenceResult directly
        if isinstance(trail, EvidenceResult):
            trail = self._coerce_trail(trail)
        result = trail.result  # type: ignore[union-attr]
        remaining_budget = self._max_evidence - len(context.sources)
        if remaining_budget <= 0:
            return trail

        target_k = min(self._builder.top_k, remaining_budget)
        missing_query = (result.missing or "").strip() or query
        try:
            targeted_results = self._retriever.search(missing_query, target_k)
        except Exception:
            # Retrieval failure degrades cleanly to the phase-6 verdict
            # instead of losing the partial answer we already have.
            return trail
        targeted_hits = targeted_results.get("hits", [])

        known_ids = {source.chunk_id for source in context.sources}
        if not any(hit.get("chunk_id") not in known_ids for hit in targeted_hits):
            return trail

        expanded_context = ContextBuilder(top_k=self._max_evidence).build(
            [*initial_hits, *targeted_hits]
        )
        new_trail = self._coerce_trail(self._generator.generate(query, expanded_context))
        self._last_context = expanded_context
        self._context_last = expanded_context
        # Stash context for callers that rely on _expand's side channel
        # (pipeline.answer now tracks this directly, so this is best-effort).
        try:
            object.__setattr__(new_trail, "_expanded_context", expanded_context)  # type: ignore[attr-defined]
        except Exception:
            pass
        return new_trail

    @property
    def top_k(self) -> int:
        """Initial sources per request (defaults to :data:`DEFAULT_TOP_K`)."""
        return self._builder.top_k

    @property
    def max_evidence(self) -> int:
        """Total distinct sources allowed across initial + targeted passes."""
        return self._max_evidence
