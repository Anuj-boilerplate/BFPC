"""Phase 3 — Evidence structures (extended by Phases 5-6).

Defines the vocabulary BFPC uses to represent evidence and relationships
between evidence. The LLM never sees free-form strings for roles or
relationship types — only these strict enums.

Phase 3 added the graph vocabulary; Phase 5 proved a generator can fill
it selectively from a fixed top-k context; Phase 6 adds sufficiency
self-assessment: :class:`EvidenceResult` now carries ``status``
(SUFFICIENT / INSUFFICIENT) and, when insufficient, a ``missing``
description of the absent evidence.

    EvidenceNode(source_id, role)
    EvidenceRelationship(from, to, type)
    EvidenceGraph(nodes, relationships)
    EvidenceResult(answer, status, missing, nodes, relationships)
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


#: Valid node roles — the only values the LLM may emit for ``role``.
Role = Literal["context", "supporting", "definition", "example", "conclusion"]

#: Valid relationship types — the only values for ``type``.
RelationshipType = Literal[
    "supports",
    "explains",
    "defines",
    "qualifies",
    "contrasts",
    "follows_from",
]

#: Whether the supplied context contained enough evidence to answer.
SufficiencyStatus = Literal["SUFFICIENT", "INSUFFICIENT"]

_VALID_ROLES: frozenset[str] = frozenset(
    {"context", "supporting", "definition", "example", "conclusion"}
)
_VALID_REL_TYPES: frozenset[str] = frozenset(
    {"supports", "explains", "defines", "qualifies", "contrasts", "follows_from"}
)


class EvidenceNode(BaseModel):
    """One evidence node: a SOURCE_N id plus its role in the answer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    role: Role

    @field_validator("source_id")
    @classmethod
    def _source_id_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source_id must not be blank")
        return value.strip()


class EvidenceRelationship(BaseModel):
    """Directed edge between two evidence nodes."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    from_id: Annotated[str, Field(alias="from")]
    to: Annotated[str, Field(alias="to")]
    type: RelationshipType  # noqa: A003 — spec field name

    @field_validator("from_id", "to")
    @classmethod
    def _endpoint_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("relationship endpoint must not be blank")
        return value.strip()


class EvidenceGraph(BaseModel):
    """Collection of nodes and their relationships."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    nodes: list[EvidenceNode] = Field(default_factory=list)
    relationships: list[EvidenceRelationship] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_graph(self) -> EvidenceGraph:
        seen: set[str] = set()
        for node in self.nodes:
            if node.source_id in seen:
                raise ValueError(f"duplicate node source_id '{node.source_id}'")
            seen.add(node.source_id)
        for rel in self.relationships:
            if rel.from_id not in seen:
                raise ValueError(f"relationship from '{rel.from_id}' has no matching node")
            if rel.to not in seen:
                raise ValueError(f"relationship to '{rel.to}' has no matching node")
            if rel.from_id == rel.to:
                raise ValueError("relationship must not be self-referential")
        return self


class EvidenceResult(BaseModel):
    """Structured output of the Generator: answer plus evidence graph.

    Phase 6 adds sufficiency self-assessment: ``status`` is SUFFICIENT
    when the supplied context contained everything needed, INSUFFICIENT
    when a necessary piece of evidence is absent — in which case
    ``missing`` describes what is missing (free text, never a source id).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    answer: str
    status: SufficiencyStatus = "SUFFICIENT"
    missing: str | None = None
    nodes: list[EvidenceNode] = Field(default_factory=list)
    relationships: list[EvidenceRelationship] = Field(default_factory=list)

    @field_validator("answer")
    @classmethod
    def _answer_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("answer must not be blank")
        return value.strip()

    @field_validator("missing")
    @classmethod
    def _missing_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("missing must not be blank when present")
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def _validate_result(self) -> EvidenceResult:
        # The two states are mutually exclusive: an insufficient verdict
        # must say what's missing; a sufficient one must not.
        if self.status == "INSUFFICIENT" and self.missing is None:
            raise ValueError("INSUFFICIENT requires a 'missing' description")
        if self.status == "SUFFICIENT" and self.missing is not None:
            raise ValueError("SUFFICIENT must not carry a 'missing' description")

        seen: set[str] = set()
        for node in self.nodes:
            if node.source_id in seen:
                raise ValueError(f"duplicate node source_id '{node.source_id}'")
            seen.add(node.source_id)
        for rel in self.relationships:
            if rel.from_id not in seen:
                raise ValueError(f"relationship from '{rel.from_id}' has no matching node")
            if rel.to not in seen:
                raise ValueError(f"relationship to '{rel.to}' has no matching node")
            if rel.from_id == rel.to:
                raise ValueError("relationship must not be self-referential")
        return self

    @property
    def graph(self) -> EvidenceGraph:
        """View this result as an :class:`EvidenceGraph`."""
        return EvidenceGraph(nodes=list(self.nodes), relationships=list(self.relationships))


class Claim(BaseModel):
    """One atomic assertion the LLM made in its answer (Phase 9)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str  # e.g. "C1", "C2"
    text: str  # the claim sentence
    required: bool = True  # must be evidenced for COMPLETE
    evidence_ids: list[str] = []  # SOURCE_N ids that back this claim
    depends_on: list[str] = []  # other Claim ids this claim builds on

    @field_validator("id", "text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Claim id/text must not be blank")
        return value.strip()
