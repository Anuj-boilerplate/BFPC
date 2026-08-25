"""Unit tests for Phase 3 evidence data structures (bfpc.context.evidence)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bfpc.context.evidence import EvidenceGraph, EvidenceNode, EvidenceRelationship, EvidenceResult


class TestEvidenceNode:
    @pytest.mark.parametrize("role", ["context", "supporting", "definition", "example", "conclusion"])
    def test_valid_role(self, role: str) -> None:
        node = EvidenceNode(source_id="SOURCE_1", role=role)
        assert node.source_id == "SOURCE_1"
        assert node.role == role

    def test_invalid_role_contradicting_raises(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceNode(source_id="SOURCE_1", role="contradicting")  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad_role", ["contradicting", "invalid", "CONTEXT", "", "support"])
    def test_invalid_role_raises(self, bad_role: str) -> None:
        with pytest.raises(ValidationError):
            EvidenceNode(source_id="SOURCE_1", role=bad_role)  # type: ignore[arg-type]

    @pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
    def test_blank_source_id_raises(self, blank: str) -> None:
        with pytest.raises(ValidationError):
            EvidenceNode(source_id=blank, role="context")

    def test_source_id_stripped(self) -> None:
        node = EvidenceNode(source_id="  SOURCE_1  ", role="context")
        assert node.source_id == "SOURCE_1"

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceNode(source_id="SOURCE_1", role="context", extra="field")  # type: ignore[call-arg]

    def test_frozen(self) -> None:
        node = EvidenceNode(source_id="SOURCE_1", role="context")
        with pytest.raises(ValidationError):
            node.source_id = "SOURCE_2"  # type: ignore[misc]

    def test_json_round_trip(self) -> None:
        node = EvidenceNode(source_id="SOURCE_1", role="supporting")
        dumped = node.model_dump()
        restored = EvidenceNode.model_validate(dumped)
        assert restored == node

    def test_json_round_trip_via_alias(self) -> None:
        node = EvidenceNode(source_id="SOURCE_2", role="definition")
        restored = EvidenceNode.model_validate(node.model_dump(by_alias=True))
        assert restored == node


class TestEvidenceRelationship:
    @pytest.mark.parametrize(
        "rel_type", ["supports", "explains", "defines", "qualifies", "contrasts", "follows_from"]
    )
    def test_valid_type_via_alias(self, rel_type: str) -> None:
        rel = EvidenceRelationship(**{"from": "SOURCE_1", "to": "SOURCE_2", "type": rel_type})  # type: ignore[arg-type]
        assert rel.from_id == "SOURCE_1"
        assert rel.to == "SOURCE_2"
        assert rel.type == rel_type

    @pytest.mark.parametrize(
        "rel_type", ["supports", "explains", "defines", "qualifies", "contrasts", "follows_from"]
    )
    def test_valid_type_via_field_name(self, rel_type: str) -> None:
        rel = EvidenceRelationship(from_id="SOURCE_1", to="SOURCE_2", type=rel_type)  # type: ignore[arg-type]
        assert rel.from_id == "SOURCE_1"
        assert rel.to == "SOURCE_2"
        assert rel.type == rel_type

    def test_alias_and_field_name_both_populate(self) -> None:
        via_alias = EvidenceRelationship(**{"from": "SOURCE_1", "to": "SOURCE_2", "type": "supports"})
        via_field = EvidenceRelationship(from_id="SOURCE_1", to="SOURCE_2", type="supports")
        assert via_alias == via_field

    def test_model_dump_by_alias_contains_from_to(self) -> None:
        rel = EvidenceRelationship(from_id="SOURCE_1", to="SOURCE_2", type="supports")
        dumped = rel.model_dump(by_alias=True)
        assert dumped["from"] == "SOURCE_1"
        assert dumped["to"] == "SOURCE_2"
        assert dumped["type"] == "supports"
        assert "from_id" not in dumped

    def test_model_dump_without_alias_contains_from_id(self) -> None:
        rel = EvidenceRelationship(from_id="SOURCE_1", to="SOURCE_2", type="supports")
        dumped = rel.model_dump()
        assert dumped["from_id"] == "SOURCE_1"
        assert dumped["to"] == "SOURCE_2"

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceRelationship(**{"from": "SOURCE_1", "to": "SOURCE_2", "type": "contradicting"})  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad", ["contradicts", "invalid", "", "SUPPORTS", "follows"])
    def test_invalid_type_various_raise(self, bad: str) -> None:
        with pytest.raises(ValidationError):
            EvidenceRelationship(from_id="SOURCE_1", to="SOURCE_2", type=bad)  # type: ignore[arg-type]

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_blank_from_raises(self, blank: str) -> None:
        with pytest.raises(ValidationError):
            EvidenceRelationship(**{"from": blank, "to": "SOURCE_2", "type": "supports"})

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_blank_to_raises(self, blank: str) -> None:
        with pytest.raises(ValidationError):
            EvidenceRelationship(**{"from": "SOURCE_1", "to": blank, "type": "supports"})

    def test_endpoints_stripped(self) -> None:
        rel = EvidenceRelationship(**{"from": "  SOURCE_1  ", "to": "  SOURCE_2  ", "type": "supports"})
        assert rel.from_id == "SOURCE_1"
        assert rel.to == "SOURCE_2"

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceRelationship(from_id="SOURCE_1", to="SOURCE_2", type="supports", extra="x")  # type: ignore[call-arg]

    def test_frozen(self) -> None:
        rel = EvidenceRelationship(from_id="SOURCE_1", to="SOURCE_2", type="supports")
        with pytest.raises(ValidationError):
            rel.to = "SOURCE_3"  # type: ignore[misc]

    def test_json_round_trip_via_alias(self) -> None:
        rel = EvidenceRelationship(**{"from": "SOURCE_1", "to": "SOURCE_2", "type": "explains"})
        dumped = rel.model_dump(by_alias=True)
        restored = EvidenceRelationship.model_validate(dumped)
        assert restored == rel

    def test_json_round_trip_via_field_name(self) -> None:
        rel = EvidenceRelationship(from_id="SOURCE_1", to="SOURCE_2", type="defines")
        dumped = rel.model_dump()
        restored = EvidenceRelationship.model_validate(dumped)
        assert restored == rel


class TestEvidenceGraph:
    def test_valid_graph(self) -> None:
        nodes = [
            EvidenceNode(source_id="SOURCE_1", role="context"),
            EvidenceNode(source_id="SOURCE_2", role="supporting"),
        ]
        rels = [EvidenceRelationship(from_id="SOURCE_1", to="SOURCE_2", type="supports")]
        graph = EvidenceGraph(nodes=nodes, relationships=rels)
        assert len(graph.nodes) == 2
        assert len(graph.relationships) == 1

    def test_empty_graph_allowed(self) -> None:
        graph = EvidenceGraph(nodes=[], relationships=[])
        assert graph.nodes == []
        assert graph.relationships == []

    def test_default_empty_graph(self) -> None:
        graph = EvidenceGraph()
        assert graph.nodes == []
        assert graph.relationships == []

    def test_duplicate_source_id_rejected(self) -> None:
        nodes = [
            EvidenceNode(source_id="SOURCE_1", role="context"),
            EvidenceNode(source_id="SOURCE_1", role="supporting"),
        ]
        with pytest.raises(ValidationError):
            EvidenceGraph(nodes=nodes, relationships=[])

    def test_duplicate_source_id_across_three_nodes(self) -> None:
        nodes = [
            EvidenceNode(source_id="SOURCE_1", role="context"),
            EvidenceNode(source_id="SOURCE_2", role="supporting"),
            EvidenceNode(source_id="SOURCE_2", role="definition"),
        ]
        with pytest.raises(ValidationError):
            EvidenceGraph(nodes=nodes, relationships=[])

    def test_relationship_missing_from_node_rejected(self) -> None:
        nodes = [EvidenceNode(source_id="SOURCE_1", role="context")]
        rels = [EvidenceRelationship(from_id="SOURCE_99", to="SOURCE_1", type="supports")]
        with pytest.raises(ValidationError):
            EvidenceGraph(nodes=nodes, relationships=rels)

    def test_relationship_missing_to_node_rejected(self) -> None:
        nodes = [EvidenceNode(source_id="SOURCE_1", role="context")]
        rels = [EvidenceRelationship(from_id="SOURCE_1", to="SOURCE_99", type="supports")]
        with pytest.raises(ValidationError):
            EvidenceGraph(nodes=nodes, relationships=rels)

    def test_relationship_both_endpoints_missing_rejected(self) -> None:
        nodes = [EvidenceNode(source_id="SOURCE_1", role="context")]
        rels = [EvidenceRelationship(from_id="SOURCE_2", to="SOURCE_3", type="supports")]
        with pytest.raises(ValidationError):
            EvidenceGraph(nodes=nodes, relationships=rels)

    def test_self_referential_rejected(self) -> None:
        nodes = [EvidenceNode(source_id="SOURCE_1", role="context")]
        rels = [EvidenceRelationship(from_id="SOURCE_1", to="SOURCE_1", type="supports")]
        with pytest.raises(ValidationError):
            EvidenceGraph(nodes=nodes, relationships=rels)

    def test_valid_graph_with_multiple_relationships(self) -> None:
        nodes = [
            EvidenceNode(source_id="SOURCE_1", role="context"),
            EvidenceNode(source_id="SOURCE_2", role="supporting"),
            EvidenceNode(source_id="SOURCE_3", role="conclusion"),
        ]
        rels = [
            EvidenceRelationship(from_id="SOURCE_1", to="SOURCE_2", type="supports"),
            EvidenceRelationship(from_id="SOURCE_2", to="SOURCE_3", type="follows_from"),
        ]
        graph = EvidenceGraph(nodes=nodes, relationships=rels)
        assert len(graph.relationships) == 2

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceGraph(nodes=[], relationships=[], extra="field")  # type: ignore[call-arg]

    def test_frozen(self) -> None:
        graph = EvidenceGraph(nodes=[EvidenceNode(source_id="SOURCE_1", role="context")])
        with pytest.raises(ValidationError):
            graph.nodes = []  # type: ignore[misc]

    def test_json_round_trip(self) -> None:
        valid = EvidenceGraph(
            nodes=[
                EvidenceNode(source_id="SOURCE_1", role="context"),
                EvidenceNode(source_id="SOURCE_2", role="supporting"),
            ],
            relationships=[EvidenceRelationship(from_id="SOURCE_1", to="SOURCE_2", type="supports")],
        )
        dumped = valid.model_dump(by_alias=True)
        restored = EvidenceGraph.model_validate(dumped)
        assert restored == valid

    def test_json_round_trip_empty(self) -> None:
        graph = EvidenceGraph()
        dumped = graph.model_dump(by_alias=True)
        restored = EvidenceGraph.model_validate(dumped)
        assert restored == graph

    def test_json_round_trip_without_alias(self) -> None:
        graph = EvidenceGraph(
            nodes=[EvidenceNode(source_id="SOURCE_1", role="example")],
            relationships=[],
        )
        dumped = graph.model_dump()
        restored = EvidenceGraph.model_validate(dumped)
        assert restored == graph


class TestEvidenceResult:
    def test_valid_result(self) -> None:
        result = EvidenceResult(
            answer="The answer is 42.",
            nodes=[EvidenceNode(source_id="SOURCE_1", role="supporting")],
            relationships=[],
        )
        assert result.answer == "The answer is 42."
        assert len(result.nodes) == 1

    def test_empty_graph_allowed_with_answer(self) -> None:
        result = EvidenceResult(answer="No evidence needed.", nodes=[], relationships=[])
        assert result.nodes == []
        assert result.relationships == []

    def test_default_empty_graph_with_answer(self) -> None:
        result = EvidenceResult(answer="Answer only.")
        assert result.nodes == []
        assert result.relationships == []

    @pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
    def test_blank_answer_rejected(self, blank: str) -> None:
        with pytest.raises(ValidationError):
            EvidenceResult(answer=blank, nodes=[], relationships=[])

    def test_answer_stripped(self) -> None:
        result = EvidenceResult(answer="  hello world  ", nodes=[], relationships=[])
        assert result.answer == "hello world"

    def test_duplicate_source_id_rejected(self) -> None:
        nodes = [
            EvidenceNode(source_id="SOURCE_1", role="context"),
            EvidenceNode(source_id="SOURCE_1", role="supporting"),
        ]
        with pytest.raises(ValidationError):
            EvidenceResult(answer="ans", nodes=nodes, relationships=[])

    def test_relationship_missing_from_node_rejected(self) -> None:
        nodes = [EvidenceNode(source_id="SOURCE_1", role="context")]
        rels = [EvidenceRelationship(from_id="SOURCE_2", to="SOURCE_1", type="supports")]
        with pytest.raises(ValidationError):
            EvidenceResult(answer="ans", nodes=nodes, relationships=rels)

    def test_relationship_missing_to_node_rejected(self) -> None:
        nodes = [EvidenceNode(source_id="SOURCE_1", role="context")]
        rels = [EvidenceRelationship(from_id="SOURCE_1", to="SOURCE_2", type="supports")]
        with pytest.raises(ValidationError):
            EvidenceResult(answer="ans", nodes=nodes, relationships=rels)

    def test_self_referential_rejected(self) -> None:
        nodes = [EvidenceNode(source_id="SOURCE_1", role="context")]
        rels = [EvidenceRelationship(from_id="SOURCE_1", to="SOURCE_1", type="supports")]
        with pytest.raises(ValidationError):
            EvidenceResult(answer="ans", nodes=nodes, relationships=rels)

    def test_graph_property_returns_evidence_graph(self) -> None:
        nodes = [
            EvidenceNode(source_id="SOURCE_1", role="context"),
            EvidenceNode(source_id="SOURCE_2", role="supporting"),
        ]
        rels = [EvidenceRelationship(from_id="SOURCE_1", to="SOURCE_2", type="explains")]
        result = EvidenceResult(answer="Answer text.", nodes=nodes, relationships=rels)
        graph = result.graph
        assert isinstance(graph, EvidenceGraph)
        assert graph.nodes == result.nodes
        assert graph.relationships == result.relationships

    def test_graph_property_empty(self) -> None:
        result = EvidenceResult(answer="Answer.", nodes=[], relationships=[])
        graph = result.graph
        assert isinstance(graph, EvidenceGraph)
        assert graph.nodes == []
        assert graph.relationships == []

    def test_graph_property_is_copy(self) -> None:
        result = EvidenceResult(
            answer="Ans",
            nodes=[EvidenceNode(source_id="SOURCE_1", role="context")],
            relationships=[],
        )
        graph = result.graph
        assert graph.nodes == result.nodes
        assert graph.nodes is not result.nodes

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceResult(answer="ans", nodes=[], relationships=[], extra="field")  # type: ignore[call-arg]

    def test_frozen(self) -> None:
        result = EvidenceResult(answer="ans", nodes=[], relationships=[])
        with pytest.raises(ValidationError):
            result.answer = "new"  # type: ignore[misc]

    def test_json_round_trip(self) -> None:
        result = EvidenceResult(
            answer="Final answer.",
            nodes=[
                EvidenceNode(source_id="SOURCE_1", role="context"),
                EvidenceNode(source_id="SOURCE_2", role="conclusion"),
            ],
            relationships=[EvidenceRelationship(from_id="SOURCE_1", to="SOURCE_2", type="follows_from")],
        )
        dumped = result.model_dump(by_alias=True)
        restored = EvidenceResult.model_validate(dumped)
        assert restored == result

    def test_json_round_trip_empty(self) -> None:
        result = EvidenceResult(answer="Only answer.")
        dumped = result.model_dump(by_alias=True)
        restored = EvidenceResult.model_validate(dumped)
        assert restored == result

    def test_json_round_trip_without_alias(self) -> None:
        result = EvidenceResult(
            answer="Answer.",
            nodes=[EvidenceNode(source_id="SOURCE_1", role="example")],
            relationships=[],
        )
        dumped = result.model_dump()
        restored = EvidenceResult.model_validate(dumped)
        assert restored == result


class TestExtraFieldsForbidden:
    def test_node_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceNode(source_id="SOURCE_1", role="context", foo="bar")  # type: ignore[call-arg]

    def test_relationship_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceRelationship(from_id="SOURCE_1", to="SOURCE_2", type="supports", foo="bar")  # type: ignore[call-arg]

    def test_graph_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceGraph(nodes=[], relationships=[], foo="bar")  # type: ignore[call-arg]

    def test_result_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceResult(answer="ans", nodes=[], relationships=[], foo="bar")  # type: ignore[call-arg]


class TestJsonRoundTrip:
    def test_node_round_trip(self) -> None:
        for role in ["context", "supporting", "definition", "example", "conclusion"]:
            node = EvidenceNode(source_id="SOURCE_1", role=role)  # type: ignore[arg-type]
            assert EvidenceNode.model_validate(node.model_dump()) == node
            assert EvidenceNode.model_validate(node.model_dump(by_alias=True)) == node

    def test_relationship_round_trip_all_types(self) -> None:
        for rel_type in ["supports", "explains", "defines", "qualifies", "contrasts", "follows_from"]:
            rel = EvidenceRelationship(from_id="SOURCE_1", to="SOURCE_2", type=rel_type)  # type: ignore[arg-type]
            assert EvidenceRelationship.model_validate(rel.model_dump()) == rel
            assert EvidenceRelationship.model_validate(rel.model_dump(by_alias=True)) == rel

    def test_graph_round_trip(self) -> None:
        graph = EvidenceGraph(
            nodes=[
                EvidenceNode(source_id="SOURCE_1", role="definition"),
                EvidenceNode(source_id="SOURCE_2", role="example"),
            ],
            relationships=[EvidenceRelationship(from_id="SOURCE_1", to="SOURCE_2", type="defines")],
        )
        assert EvidenceGraph.model_validate(graph.model_dump()) == graph
        assert EvidenceGraph.model_validate(graph.model_dump(by_alias=True)) == graph

    def test_result_round_trip(self) -> None:
        result = EvidenceResult(
            answer="Comprehensive answer.",
            nodes=[
                EvidenceNode(source_id="SOURCE_1", role="context"),
                EvidenceNode(source_id="SOURCE_2", role="supporting"),
                EvidenceNode(source_id="SOURCE_3", role="conclusion"),
            ],
            relationships=[
                EvidenceRelationship(from_id="SOURCE_1", to="SOURCE_2", type="supports"),
                EvidenceRelationship(from_id="SOURCE_2", to="SOURCE_3", type="follows_from"),
            ],
        )
        assert EvidenceResult.model_validate(result.model_dump()) == result
        assert EvidenceResult.model_validate(result.model_dump(by_alias=True)) == result

    def test_result_round_trip_graph_consistency(self) -> None:
        result = EvidenceResult(
            answer="Answer.",
            nodes=[EvidenceNode(source_id="SOURCE_1", role="context")],
            relationships=[],
        )
        dumped = result.model_dump(by_alias=True)
        restored = EvidenceResult.model_validate(dumped)
        assert restored.graph == result.graph
