"""Generator contract: the single interface between BFPC and any LLM.

The rest of the application depends only on :class:`Generator`; concrete
providers (Gemini, mocks, future models) live behind it and are chosen by
configuration (:mod:`bfpc.context.factory`). A generator's entire world is
the query plus the sanitized :class:`bfpc.context.builder.LLMContext` —
it knows nothing about FAISS, embeddings, PDFs, bboxes, rects or
retrieval scores.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from bfpc.context.builder import LLMContext

# Imported at type-checking time to avoid cycles; runtime import inside
# methods where needed. Using string annotation for EvidenceResult.
if False:  # pragma: no cover
    from bfpc.context.completeness import TrailReport
    from bfpc.context.evidence import EvidenceResult


class GeneratorError(RuntimeError):
    """Raised when the configured generator cannot produce an answer."""


class InvalidCitationError(GeneratorError):
    """LLM referenced a SOURCE_N id that was never supplied in the context."""


class Generator(ABC):
    """Generation boundary: ``(query, LLMContext) -> structured evidence``.

    Phase 4 changes the output from plain text to :class:`EvidenceResult`
    (answer + nodes + relationships). Phase 9 wraps that in
    :class:`TrailReport` (result + claims + completeness report).
    """

    @abstractmethod
    def generate(self, query: str, context: LLMContext) -> TrailReport:  # type: ignore[name-defined]
        """Produce a structured answer for *query* given *context*.

        Implementations must treat ``context.sources`` as the only
        admissible knowledge, validate that every ``source_id`` in the
        returned graph was supplied, and must not mutate the context.

        :raises GeneratorError: when no answer can be produced.
        :raises InvalidCitationError: when the LLM references an unknown source.
        """
