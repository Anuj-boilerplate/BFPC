"""Phase 9 — Deterministic completeness checker.

Pure post-generation checker that re-evaluates the LLM's output against
4 objective rules. No retrieval, no I/O, no network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bfpc.context.builder import LLMContext
from bfpc.context.evidence import Claim, EvidenceResult

# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompletenessReport:
    """Result of the 4-rule completeness check."""

    complete: bool
    reasons: list[str]  # human-readable failure explanations
    uncovered_claims: list[str]  # Claim.id values that failed Rule 2
    unresolved_deps: list[str]  # Claim.id values that failed Rule 3


@dataclass(frozen=True)
class TrailReport:
    """Wrapper keeping :class:`EvidenceResult` frozen plus claims & report.

    Phase 8 wire format (EvidenceResult) is untouched — this wrapper is
    the Phase 9 addition and is trivially rollback-able.
    """

    result: EvidenceResult  # the original Phase 8 output, unchanged
    claims: list[Claim]  # LLM-emitted claims ([] if LLM omitted them)
    report: CompletenessReport

    # -- Delegation for backward compat: allow ``trail.answer`` etc --------
    @property  # type: ignore[no-redef]
    def answer(self) -> str:  # type: ignore[override]
        return self.result.answer

    @property
    def status(self):  # type: ignore[no-redef]
        return self.result.status

    @property
    def missing(self):  # type: ignore[no-redef]
        return self.result.missing

    @property
    def nodes(self):  # type: ignore[no-redef]
        return self.result.nodes

    @property
    def relationships(self):  # type: ignore[no-redef]
        return self.result.relationships

    @property
    def graph(self):  # type: ignore[no-redef]
        return self.result.graph

    def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
        # Fallback delegation to result for any other EvidenceResult attribute
        return getattr(self.result, name)


# ---------------------------------------------------------------------------
# Pure checker
# ---------------------------------------------------------------------------

_UNKNOWN_SUBSTRINGS = ("don't know", "do not know")
_SUPPORTING_ROLES: frozenset[str] = frozenset({"supporting", "definition"})


def _is_unknown_answer(answer: str) -> bool:
    """Return True if the answer text signals 'I don't know' / unknown."""
    stripped = answer.strip()
    if not stripped:
        return True
    low = stripped.lower()
    # Phrase check — catches "I don't know", "do not know", "don't know"
    for phrase in _UNKNOWN_SUBSTRINGS:
        if phrase in low:
            return True
    if low == "unknown":
        return True
    # Common variants
    if "cannot answer" in low or "can't answer" in low or "can not answer" in low:
        return True
    # "i don't know" is already covered, but keep explicit
    if "i don't know" in low:
        return True
    return False


def _jaccard_overlap(a: str, b: str) -> bool:
    """True if token sets of a and b share at least one word (Jaccard > 0)."""
    tokens_a = set(re.findall(r"\w+", a.lower()))
    tokens_b = set(re.findall(r"\w+", b.lower()))
    if not tokens_a or not tokens_b:
        return False
    return bool(tokens_a & tokens_b)


def check(
    result: EvidenceResult,
    claims: list[Claim],
    context: LLMContext,
    budget: int,
) -> CompletenessReport:
    """Pure function. No retrieval, no I/O. Runs all 4 rules.

    :param result: original generator output
    :param claims: LLM-emitted claims (may be empty)
    :param context: LLMContext used for generation
    :param budget: pipeline max_evidence budget
    :returns: CompletenessReport (complete iff all 4 rules pass)
    """
    reasons: list[str] = []
    uncovered_claims: list[str] = []
    unresolved_deps: list[str] = []

    # -- Rule 1: Answerable ------------------------------------------------
    # answer not blank/unknown AND >=1 supporting/definition node with Jaccard overlap
    rule1_fail_reason: str | None = None
    if _is_unknown_answer(result.answer):
        rule1_fail_reason = "Rule 1 (Answerable) failed: answer is blank or signals unknown"
    else:
        supporting_nodes = [n for n in result.nodes if n.role in _SUPPORTING_ROLES]
        if not supporting_nodes:
            rule1_fail_reason = (
                "Rule 1 (Answerable) failed: no supporting or definition evidence"
            )
        else:
            # Check Jaccard overlap between answer and each supporting chunk text
            # Map source_id -> chunk text via context.sources
            source_text: dict[str, str] = {s.source_id: s.text for s in context.sources}
            has_overlap = False
            for node in supporting_nodes:
                chunk_text = source_text.get(node.source_id, "")
                if not chunk_text:
                    # Fallback: try originals if sources mapping missing (defensive)
                    orig = context.originals.get(node.source_id)
                    if orig is not None:
                        chunk_text = str(orig.get("text", ""))
                if chunk_text and _jaccard_overlap(result.answer, chunk_text):
                    has_overlap = True
                    break
                # Also try sentence_ranker as advertised data source — if any
                # sentence from the chunk has nonzero overlap, that also counts.
                # Our _jaccard_overlap already covers this (any word overlap
                # implies best sentence overlap >0), so no extra work needed.
            if not has_overlap:
                rule1_fail_reason = (
                    "Rule 1 (Answerable) failed: no supporting/definition evidence "
                    "has Jaccard overlap with the answer"
                )
    if rule1_fail_reason is not None:
        reasons.append(rule1_fail_reason)

    # -- Rule 2: Every required claim is backed ---------------------------
    # For each required claim, at least one evidence_id must map to a supporting/definition node
    supporting_ids: set[str] = {n.source_id for n in result.nodes if n.role in _SUPPORTING_ROLES}
    for claim in claims:
        if not claim.required:
            continue
        # Does at least one evidence_id point to a supporting/definition node?
        backed = any(eid in supporting_ids for eid in claim.evidence_ids)
        if not backed:
            uncovered_claims.append(claim.id)
    if uncovered_claims:
        reasons.append(
            f"Rule 2 (Claims backed) failed: required claims not backed: {', '.join(uncovered_claims)}"
        )

    # -- Rule 3: No dangling dependencies ---------------------------------
    all_ids: set[str] = {c.id for c in claims}
    missing_deps_set: set[str] = set()
    # Preserve discovery order for deterministic output, but de-duplicate
    ordered_missing: list[str] = []
    for claim in claims:
        for dep in claim.depends_on:
            if dep not in all_ids and dep not in missing_deps_set:
                missing_deps_set.add(dep)
                ordered_missing.append(dep)
    unresolved_deps = ordered_missing
    if unresolved_deps:
        reasons.append(
            f"Rule 3 (Dependencies) failed: unresolved claim dependencies: {', '.join(unresolved_deps)}"
        )

    # -- Rule 4: Within budget ---------------------------------------------
    if len(context.sources) > budget:
        reasons.append(
            f"Rule 4 (Budget) failed: {len(context.sources)} sources exceeds budget {budget}"
        )

    complete = not reasons
    return CompletenessReport(
        complete=complete,
        reasons=reasons,
        uncovered_claims=uncovered_claims,
        unresolved_deps=unresolved_deps,
    )
