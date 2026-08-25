"""LLM answer pipeline: Phases 1-4.

Phase 1 (:class:`bfpc.context.ContextBuilder`) turns validated retrieval
results (contract §5.2 hits) into an :class:`bfpc.context.LLMContext`
whose sources are capped at ``top_k``, deduplicated by ``chunk_id``, and
projected onto temporary ``SOURCE_N`` ids.

Phase 2 (:class:`bfpc.context.base.Generator`) is the single boundary to
LLM generation: ``(query, LLMContext) -> EvidenceResult``.

Phase 3 (:mod:`bfpc.context.evidence`) defines the evidence vocabulary:
:class:`EvidenceNode`, :class:`EvidenceRelationship`,
:class:`EvidenceGraph`, :class:`EvidenceResult`.

Phase 4 makes the generator emit structured JSON with validation that
only supplied ``SOURCE_N`` ids may be referenced.
"""

from __future__ import annotations

from bfpc.context.base import Generator, GeneratorError, InvalidCitationError
from bfpc.context.builder import (
    DEFAULT_TOP_K,
    ContextBuilder,
    LLMContext,
    MalformedRetrievalResult,
    Source,
)
from bfpc.context.completeness import CompletenessReport, TrailReport, check
from bfpc.context.evidence import (
    Claim,
    EvidenceGraph,
    EvidenceNode,
    EvidenceRelationship,
    EvidenceResult,
)
from bfpc.context.factory import PROVIDERS, create_generator
from bfpc.context.gemini_generator import GeminiGenerator
from bfpc.context.mock_generator import MockGenerator
from bfpc.context.pipeline import DEFAULT_MAX_EVIDENCE, AnswerPipeline

__all__ = [
    "DEFAULT_MAX_EVIDENCE",
    "DEFAULT_TOP_K",
    "PROVIDERS",
    "AnswerPipeline",
    "Claim",
    "CompletenessReport",
    "ContextBuilder",
    "EvidenceGraph",
    "EvidenceNode",
    "EvidenceRelationship",
    "EvidenceResult",
    "Generator",
    "GeneratorError",
    "GeminiGenerator",
    "InvalidCitationError",
    "LLMContext",
    "MalformedRetrievalResult",
    "MockGenerator",
    "Source",
    "TrailReport",
    "check",
    "create_generator",
]
