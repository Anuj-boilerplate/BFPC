"""Phase 1 — Context Builder: retrieval hits -> LLM-facing context.

Takes the validated Phase 0 results (contract §5.2 hits) and produces a
compact context for one LLM request: at most ``top_k`` distinct chunks,
each assigned a temporary ``SOURCE_N`` id and stripped to the five fields
the model needs (``source_id``, ``chunk_id``, ``page``, ``kind``,
``text``). Retrieval internals (``score``, ``bbox``, ``snippet``,
``rects``) never reach the LLM payload; they stay reachable through
:meth:`LLMContext.original` so a cited ``SOURCE_N`` can later be resolved
back to page / bbox / rects for highlighting.

Selection order is the retrieval order; duplicates collapse onto their
first occurrence so a repeated chunk never consumes a context slot. The
``SOURCE_N`` ids are per-request only — every fresh :class:`LLMContext`
restarts numbering at ``SOURCE_1``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

#: How many distinct retrieval results flow into one LLM request.
DEFAULT_TOP_K = 5


class MalformedRetrievalResult(ValueError):
    """A Phase 0 result is missing a required field, or it is blank."""


@dataclass(frozen=True, slots=True)
class Source:
    """LLM-facing projection of one retrieval result."""

    source_id: str
    chunk_id: str
    page: int
    kind: str
    text: str


@dataclass(frozen=True, slots=True)
class LLMContext:
    """The LLM payload plus the preserved map back to retrieval internals.

    ``sources`` is everything the model may see. ``originals`` maps each
    ``SOURCE_N`` id to the untouched Phase 0 result behind it — this is
    what turns an answer citation like "SOURCE_2" back into the actual
    PDF highlight geometry. It holds references to the caller's mappings
    and must never be serialized into a prompt.
    """

    sources: tuple[Source, ...]
    originals: Mapping[str, Mapping[str, Any]]

    def original(self, source_id: str) -> Mapping[str, Any] | None:
        """Return the full Phase 0 result behind *source_id*, or ``None``."""
        return self.originals.get(source_id)


class ContextBuilder:
    """Selects, deduplicates and projects Phase 0 results for one request."""

    def __init__(self, top_k: int = DEFAULT_TOP_K) -> None:
        if top_k < 1:
            raise ValueError(f"top_k must be >= 1, got {top_k}")
        self._top_k = top_k

    @property
    def top_k(self) -> int:
        """How many distinct sources this builder keeps per request."""
        return self._top_k

    def build(self, results: Sequence[Mapping[str, Any]]) -> LLMContext:
        """Build the LLM-facing context from validated retrieval *results*.

        Duplicates are removed by ``chunk_id`` (first occurrence wins)
        before selection, then the first :attr:`top_k` survivors are kept
        in retrieval order and numbered ``SOURCE_1 .. SOURCE_n``.

        :raises MalformedRetrievalResult: when a consumed field
            (``chunk_id``, ``text``, ``page``, ``kind``) is missing or blank.
        """
        selected = self._select_distinct_top_k(results)
        sources = tuple(
            Source(
                source_id=f"SOURCE_{position}",
                chunk_id=self._required(result, "chunk_id", position),
                page=self._required(result, "page", position),
                kind=self._required(result, "kind", position),
                text=self._required(result, "text", position),
            )
            for position, result in enumerate(selected, start=1)
        )
        originals = {source.source_id: result for source, result in zip(sources, selected)}
        return LLMContext(sources=sources, originals=originals)

    def _select_distinct_top_k(self, results: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        selected: list[Mapping[str, Any]] = []
        seen: set[str] = set()
        for index, result in enumerate(results):
            if len(selected) >= self._top_k:
                break
            chunk_id = self._required(result, "chunk_id", index)
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            selected.append(result)
        return selected

    @staticmethod
    def _required(result: Mapping[str, Any], name: str, position: int) -> Any:
        try:
            value = result[name]
        except (KeyError, TypeError) as exc:
            raise MalformedRetrievalResult(
                f"retrieval result #{position} is missing required field '{name}'"
            ) from exc
        if isinstance(value, str) and not value.strip():
            raise MalformedRetrievalResult(
                f"retrieval result #{position} has blank required field '{name}'"
            )
        return value
