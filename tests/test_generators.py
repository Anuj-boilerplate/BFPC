"""Phase 4 tests: Generator contract, implementations, factory, pipeline.

Structured output: ``Generator.generate(query, LLMContext) -> EvidenceResult``
with strict citation validation. Gemini is exercised through
``httpx.MockTransport`` (no network), the same technique as
tests/test_embedder_api.py.
"""

from __future__ import annotations

import json

import httpx
import pytest

from bfpc.context import (
    AnswerPipeline,
    Claim,
    CompletenessReport,
    ContextBuilder,
    EvidenceResult,
    Generator,
    GeneratorError,
    GeminiGenerator,
    InvalidCitationError,
    MockGenerator,
    TrailReport,
    create_generator,
)


_BASE = "https://example.test/v1beta"


def _result(chunk_id: str, **overrides) -> dict:
    """One Phase 0 hit in the contract §5.2 shape."""
    result: dict = {
        "chunk_id": chunk_id,
        "text": f"text of {chunk_id} mock gemini structured ok recovered packet loss final combined",
        "page": 43,
        "kind": "text",
        "score": 0.73,
        "bbox": [45.0, 520.0, 400.0, 545.0],
        "snippet": f"best sentence of {chunk_id}",
        "rects": [[45.0, 523.5, 60.1, 535.8]],
    }
    result.update(overrides)
    return result


def _unwrap(result):
    """Helper: get EvidenceResult from either EvidenceResult or TrailReport."""
    if isinstance(result, TrailReport):
        return result.result
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


def _reply(
    answer: str = "ok",
    nodes: list[dict] | None = None,
    relationships: list[dict] | None = None,
    *,
    raw_text: str | None = None,
) -> dict:
    """Gemini ``generateContent`` payload whose ``parts[0].text`` is JSON.

    By default encodes ``{"answer": answer, "nodes": ..., "relationships": ...}``
    as ``json.dumps`` — matching Phase 4 ``responseMimeType: application/json``.
    Pass ``raw_text`` to force invalid JSON or fenced payloads.
    """
    if raw_text is not None:
        text = raw_text
    else:
        payload = {
            "answer": answer,
            "nodes": nodes if nodes is not None else [],
            "relationships": relationships if relationships is not None else [],
        }
        text = json.dumps(payload)
    return {"candidates": [{"content": {"parts": [{"text": text}], "role": "model"}}]}


class TestContract:
    def test_mock_satisfies_generator(self) -> None:
        assert isinstance(MockGenerator(), Generator)

    def test_gemini_satisfies_generator(self) -> None:
        generator = _gemini(lambda request: httpx.Response(200, json=_reply("ok")))
        assert isinstance(generator, Generator)

    def test_generate_signature_returns_evidence_result(self) -> None:
        result = MockGenerator().generate("q?", _context())
        assert isinstance(result, (EvidenceResult, TrailReport))
        assert isinstance(_unwrap(result).answer, str)

    def test_gemini_generate_returns_evidence_result(self) -> None:
        result = _gemini(lambda request: httpx.Response(200, json=_reply("gemini ok"))).generate(
            "q?", _context()
        )
        assert isinstance(result, (EvidenceResult, TrailReport))
        assert _unwrap(result).answer == "gemini ok"


class TestMockGenerator:
    def test_default_reply_names_query_and_sources(self) -> None:
        result = MockGenerator().generate("what changed?", _context())
        assert isinstance(result, (EvidenceResult, TrailReport))
        r = _unwrap(result)
        assert "[mock]" in r.answer
        assert "what changed?" in r.answer
        assert "SOURCE_1" in r.answer
        # default mock cites first source as supporting
        assert len(r.nodes) == 1
        assert r.nodes[0].source_id == "SOURCE_1"
        assert r.nodes[0].role == "supporting"
        assert r.relationships == []

    def test_default_reply_no_sources(self) -> None:
        result = MockGenerator().generate("q?", _context(0))
        assert isinstance(result, (EvidenceResult, TrailReport))
        r = _unwrap(result)
        assert "no sources" in r.answer
        assert r.nodes == []
        assert r.relationships == []

    def test_canned_str_reply_coerced_to_evidence_result(self) -> None:
        result = MockGenerator(reply="fixed").generate("anything", _context())
        assert isinstance(result, (EvidenceResult, TrailReport))
        r = _unwrap(result)
        assert r.answer == "fixed"
        assert r.nodes == []
        assert r.relationships == []

    def test_canned_dict_reply_validated_to_evidence_result(self) -> None:
        canned = {
            "answer": "dict answer",
            "nodes": [{"source_id": "SOURCE_1", "role": "definition"}],
            "relationships": [],
        }
        result = MockGenerator(reply=canned).generate("q", _context())
        assert isinstance(result, (EvidenceResult, TrailReport))
        r = _unwrap(result)
        assert r.answer == "dict answer"
        assert len(r.nodes) == 1
        assert r.nodes[0].source_id == "SOURCE_1"
        assert r.nodes[0].role == "definition"

    def test_canned_evidence_result_preserved(self) -> None:
        expected = EvidenceResult(
            answer="direct",
            nodes=[],
            relationships=[],
        )
        result = MockGenerator(reply=expected).generate("q", _context())
        assert _unwrap(result) is expected or _unwrap(result) == expected

    def test_canned_evidence_result_with_graph_preserved(self) -> None:
        expected = EvidenceResult(
            answer="with graph",
            nodes=[{"source_id": "SOURCE_1", "role": "supporting"}],  # type: ignore[arg-type]
            relationships=[],
        )
        # validate via model_validate to ensure proper type
        expected = EvidenceResult.model_validate(expected.model_dump())
        result = MockGenerator(reply=expected).generate("q", _context(1))
        assert _unwrap(result) == expected

    def test_callable_str_reply_receives_inputs_and_coerced(self) -> None:
        seen: dict = {}

        def render(query: str, context) -> str:
            seen["query"] = query
            seen["sources"] = len(context.sources)
            return "done"

        result = MockGenerator(reply=render).generate("q", _context())
        assert seen == {"query": "q", "sources": 3}
        assert isinstance(result, (EvidenceResult, TrailReport))
        assert _unwrap(result).answer == "done"
        assert _unwrap(result).nodes == []

    def test_callable_dict_reply_coerced(self) -> None:
        def render(query: str, context):
            return {"answer": f"echo {query}", "nodes": [], "relationships": []}

        result = MockGenerator(reply=render).generate("hello", _context())
        assert isinstance(result, (EvidenceResult, TrailReport))
        assert _unwrap(result).answer == "echo hello"

    def test_callable_evidence_result_passthrough(self) -> None:
        expected = EvidenceResult(answer="from callable", nodes=[], relationships=[])

        def render(query, context):
            return expected

        result = MockGenerator(reply=render).generate("q", _context())
        assert _unwrap(result) is expected

    def test_callable_returning_evidence_result_with_nodes(self) -> None:
        def render(query: str, context):
            return EvidenceResult(
                answer="callable graph",
                nodes=[{"source_id": "SOURCE_2", "role": "context"}],  # type: ignore[arg-type]
                relationships=[],
            )

        result = MockGenerator(reply=render).generate("q", _context(2))
        assert _unwrap(result).answer == "callable graph"
        assert _unwrap(result).nodes[0].source_id == "SOURCE_2"

    def test_records_calls_for_assertions(self) -> None:
        generator = MockGenerator()
        context = _context()
        generator.generate("q1", context)
        assert generator.calls == [("q1", context)]

    def test_multiple_calls_tracked(self) -> None:
        generator = MockGenerator()
        c1 = _context(1)
        c2 = _context(2)
        generator.generate("q1", c1)
        generator.generate("q2", c2)
        assert len(generator.calls) == 2
        assert generator.calls[0] == ("q1", c1)
        assert generator.calls[1] == ("q2", c2)


class TestGeminiGenerator:
    def test_request_shape_and_answer_extraction(self) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["key"] = request.headers["x-goog-api-key"]
            seen["payload"] = json.loads(request.content)
            return httpx.Response(200, json=_reply("packet loss causes it"))

        result = _gemini(handler).generate("why drops?", _context(2))
        assert isinstance(result, (EvidenceResult, TrailReport))
        assert result.answer == "packet loss causes it"
        assert result.nodes == []
        assert seen["url"] == f"{_BASE}/models/gemini-2.5-flash:generateContent"
        assert seen["key"] == "test-key"
        payload = seen["payload"]
        assert payload["generationConfig"]["temperature"] == 0.2
        assert payload["generationConfig"]["responseMimeType"] == "application/json"
        assert "responseSchema" in payload["generationConfig"]
        schema = payload["generationConfig"]["responseSchema"]
        assert "answer" in schema["properties"]
        assert "status" in schema["properties"]
        assert "nodes" in schema["properties"]
        assert "relationships" in schema["properties"]
        assert "systemInstruction" in payload
        assert payload["systemInstruction"]["parts"][0]["text"]
        user_text = payload["contents"][0]["parts"][0]["text"]
        assert "Question: why drops?" in user_text
        for index in range(1, 3):
            assert f"[SOURCE_{index}]" in user_text
            assert f"text of chunk_{index}" in user_text

    def test_request_includes_system_instruction_and_response_schema(self) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["payload"] = json.loads(request.content)
            return httpx.Response(200, json=_reply("ok"))

        _gemini(handler).generate("q", _context(1))
        payload = seen["payload"]
        assert payload["generationConfig"]["responseMimeType"] == "application/json"
        schema = payload["generationConfig"]["responseSchema"]
        assert schema["required"] == ["answer", "status", "nodes", "relationships"]
        status_enum = schema["properties"]["status"]["enum"]
        assert set(status_enum) == {"SUFFICIENT", "INSUFFICIENT"}
        assert "missing" in schema["properties"]
        nodes_role_enum = schema["properties"]["nodes"]["items"]["properties"]["role"]["enum"]
        assert set(nodes_role_enum) == {
            "context",
            "supporting",
            "definition",
            "example",
            "conclusion",
        }
        rel_type_enum = schema["properties"]["relationships"]["items"]["properties"]["type"][
            "enum"
        ]
        assert set(rel_type_enum) == {
            "supports",
            "explains",
            "defines",
            "qualifies",
            "contrasts",
            "follows_from",
        }
        system_text = payload["systemInstruction"]["parts"][0]["text"]
        assert "Select ONLY the passages necessary" in system_text
        assert "appropriate role" in system_text
        assert "Never invent source ids" in system_text
        assert "SUFFICIENT" in system_text
        assert "INSUFFICIENT" in system_text
        assert "'missing'" in system_text

    def test_source_excerpts_include_page_and_kind(self) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["payload"] = json.loads(request.content)
            return httpx.Response(200, json=_reply("ok"))

        _gemini(handler).generate("q", _context(1))
        user_text = seen["payload"]["contents"][0]["parts"][0]["text"]
        # format is "[SOURCE_1] (page 43, text)\ntext of chunk_1"
        assert "[SOURCE_1] (page 43, text)" in user_text
        assert "text of chunk_1" in user_text

    def test_boundary_internal_fields_never_reach_the_prompt(self) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["raw"] = request.content.decode("utf-8")
            return httpx.Response(200, json=_reply("ok"))

        result = _gemini(handler).generate("q", _context())
        assert isinstance(result, (EvidenceResult, TrailReport))
        # The prompt may contain source *text*, but none of the retrieval
        # internals (score / bbox / snippet / rects values) may leak.
        for internal in ("0.73", "best sentence of", "45.0", "520.0", "523.5", "535.8"):
            assert internal not in seen["raw"]

    def test_model_selection_follows_constructor(self) -> None:
        urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            urls.append(str(request.url))
            return httpx.Response(200, json=_reply("ok"))

        generator = GeminiGenerator(
            model="gemini-custom",
            base_url=_BASE,
            api_key="k",
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        result = generator.generate("q", _context())
        assert isinstance(result, (EvidenceResult, TrailReport))
        assert urls == [f"{_BASE}/models/gemini-custom:generateContent"]

    def test_client_is_created_once_and_shared(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, json=_reply("ok"))

        generator = _gemini(handler)
        first = generator._client
        generator.generate("q1", _context())
        generator.generate("q2", _context())
        assert generator._client is first
        assert calls["n"] == 2

    def test_multi_part_response_is_joined(self) -> None:
        data = {
            "candidates": [
                {"content": {"parts": [{"text": "part one "}, {"text": "part two"}]}}
            ]
        }
        assert GeminiGenerator._extract(data) == "part one part two"
        assert GeminiGenerator._extract_text(data) == "part one part two"

    def test_multi_part_json_is_joined_before_parsing(self) -> None:
        part1 = '{"answer": "hello '
        part2 = 'world", "nodes": [], "relationships": []}'
        data = {
            "candidates": [
                {"content": {"parts": [{"text": part1}, {"text": part2}], "role": "model"}}
            ]
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=data)

        result = _gemini(handler).generate("q", _context())
        assert isinstance(result, (EvidenceResult, TrailReport))
        assert result.answer == "hello world"

    def test_rate_limit_retries_then_succeeds(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(429, text="quota")
            return httpx.Response(200, json=_reply("recovered"))

        generator = GeminiGenerator(
            base_url=_BASE,
            api_key="k",
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            retry_delays=(0.0,),
        )
        result = generator.generate("q", _context())
        assert isinstance(result, (EvidenceResult, TrailReport))
        assert result.answer == "recovered"
        assert calls["n"] == 2

    def test_rate_limit_retry_preserves_structured_output(self) -> None:
        calls = {"n": 0}
        nodes = [{"source_id": "SOURCE_1", "role": "supporting"}]

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(500, text="server error")
            return httpx.Response(
                200, json=_reply(answer="after retry", nodes=nodes, relationships=[])
            )

        generator = GeminiGenerator(
            base_url=_BASE,
            api_key="k",
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            retry_delays=(0.0,),
        )
        result = generator.generate("q", _context(1))
        assert result.answer == "after retry"
        assert result.nodes[0].source_id == "SOURCE_1"
        assert calls["n"] == 2

    def test_client_error_fails_fast_without_retry(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(400, text="bad request")

        generator = GeminiGenerator(
            base_url=_BASE,
            api_key="k",
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            retry_delays=(0.0, 0.0),
        )
        with pytest.raises(GeneratorError, match="400"):
            generator.generate("q", _context())
        assert calls["n"] == 1

    def test_blocked_prompt_raises(self) -> None:
        data = {"promptFeedback": {"blockReason": "SAFETY"}}
        with pytest.raises(GeneratorError, match="SAFETY"):
            GeminiGenerator._extract(data)
        with pytest.raises(GeneratorError, match="SAFETY"):
            GeminiGenerator._extract_text(data)

    def test_no_candidates_raises(self) -> None:
        with pytest.raises(GeneratorError, match="no candidates"):
            GeminiGenerator._extract({"candidates": []})
        with pytest.raises(GeneratorError, match="no candidates"):
            GeminiGenerator._extract_text({"candidates": []})

    def test_empty_completion_raises_with_finish_reason(self) -> None:
        data = {"candidates": [{"finishReason": "RECITATION", "content": {"parts": []}}]}
        with pytest.raises(GeneratorError, match="RECITATION"):
            GeminiGenerator._extract(data)
        with pytest.raises(GeneratorError, match="RECITATION"):
            GeminiGenerator._extract_text(data)

    def test_invalid_json_raises_generator_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_reply(raw_text="not json at all"))

        with pytest.raises(GeneratorError, match="invalid JSON"):
            _gemini(handler).generate("q", _context())

        def handler2(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_reply(raw_text="{bad json: }"))

        with pytest.raises(GeneratorError, match="invalid JSON"):
            _gemini(handler2).generate("q", _context())

    def test_invalid_evidence_shape_raises_generator_error(self) -> None:
        bad = {
            "answer": "bad",
            "nodes": [{"source_id": "SOURCE_1", "role": "contradicting"}],
            "relationships": [],
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_reply(raw_text=json.dumps(bad)))

        with pytest.raises(GeneratorError, match="invalid evidence shape"):
            _gemini(handler).generate("q", _context(1))

    def test_invalid_shape_does_not_trigger_citation_retry(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            bad = {
                "answer": "bad",
                "nodes": [{"source_id": "SOURCE_1", "role": "invalid_role"}],
                "relationships": [],
            }
            return httpx.Response(200, json=_reply(raw_text=json.dumps(bad)))

        with pytest.raises(GeneratorError):
            _gemini(handler).generate("q", _context(1))
        assert calls["n"] == 1

    def test_valid_structured_round_trip(self) -> None:
        nodes = [
            {"source_id": "SOURCE_1", "role": "supporting"},
            {"source_id": "SOURCE_2", "role": "context"},
        ]
        relationships = [{"from": "SOURCE_1", "to": "SOURCE_2", "type": "supports"}]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json=_reply(answer="Structured ok", nodes=nodes, relationships=relationships)
            )

        result = _gemini(handler).generate("q", _context(2))
        assert isinstance(result, (EvidenceResult, TrailReport))
        assert result.answer == "Structured ok"
        assert len(result.nodes) == 2
        assert result.nodes[0].source_id == "SOURCE_1"
        assert result.nodes[0].role == "supporting"
        assert result.nodes[1].source_id == "SOURCE_2"
        assert result.nodes[1].role == "context"
        assert len(result.relationships) == 1
        assert result.relationships[0].from_id == "SOURCE_1"
        assert result.relationships[0].to == "SOURCE_2"
        assert result.relationships[0].type == "supports"

    def test_valid_round_trip_with_all_roles_and_types(self) -> None:
        nodes = [
            {"source_id": "SOURCE_1", "role": "context"},
            {"source_id": "SOURCE_2", "role": "definition"},
            {"source_id": "SOURCE_3", "role": "example"},
        ]
        relationships = [
            {"from": "SOURCE_1", "to": "SOURCE_2", "type": "defines"},
            {"from": "SOURCE_2", "to": "SOURCE_3", "type": "explains"},
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json=_reply(answer="All types", nodes=nodes, relationships=relationships)
            )

        result = _gemini(handler).generate("q", _context(3))
        assert result.answer == "All types"
        assert len(result.nodes) == 3
        assert len(result.relationships) == 2
        assert result.relationships[0].type == "defines"
        assert result.relationships[1].type == "explains"

    def test_fenced_json_is_stripped_and_parsed(self) -> None:
        payload = {
            "answer": "fenced ok",
            "nodes": [{"source_id": "SOURCE_1", "role": "example"}],
            "relationships": [],
        }
        fenced = "```json\n" + json.dumps(payload) + "\n```"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_reply(raw_text=fenced))

        result = _gemini(handler).generate("q", _context(1))
        assert isinstance(result, (EvidenceResult, TrailReport))
        assert result.answer == "fenced ok"
        assert result.nodes[0].role == "example"

        fenced2 = "```\n" + json.dumps(payload) + "\n```"

        def handler2(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_reply(raw_text=fenced2))

        result2 = _gemini(handler2).generate("q", _context(1))
        assert result2.answer == "fenced ok"

    def test_hallucinated_source_triggers_one_retry_with_correction(self) -> None:
        payloads: list[dict] = []
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            payloads.append(json.loads(request.content))
            if calls["n"] == 1:
                return httpx.Response(
                    200,
                    json=_reply(
                        answer="bad",
                        nodes=[{"source_id": "SOURCE_99", "role": "supporting"}],
                    ),
                )
            return httpx.Response(
                200,
                json=_reply(
                    answer="fixed",
                    nodes=[{"source_id": "SOURCE_1", "role": "supporting"}],
                ),
            )

        result = _gemini(handler).generate("q", _context(2))
        assert isinstance(result, (EvidenceResult, TrailReport))
        assert result.answer == "fixed"
        assert result.nodes[0].source_id == "SOURCE_1"
        assert calls["n"] == 2
        # second request contains correction text and valid ids
        first_text = payloads[0]["contents"][0]["parts"][0]["text"]
        second_text = payloads[1]["contents"][0]["parts"][0]["text"]
        assert "Correction:" not in first_text
        assert "Correction:" in second_text
        assert "Valid sources are:" in second_text
        assert "SOURCE_1" in second_text
        assert "SOURCE_2" in second_text
        # correction should mention the hallucinated id
        assert "SOURCE_99" in second_text

    def test_hallucinated_relationship_triggers_retry(self) -> None:
        payloads: list[dict] = []
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            payloads.append(json.loads(request.content))
            if calls["n"] == 1:
                return httpx.Response(
                    200,
                    json=_reply(
                        answer="bad rel",
                        nodes=[
                            {"source_id": "SOURCE_1", "role": "context"},
                            {"source_id": "SOURCE_2", "role": "supporting"},
                        ],
                        relationships=[{"from": "SOURCE_99", "to": "SOURCE_1", "type": "supports"}],
                    ),
                )
            return httpx.Response(
                200,
                json=_reply(
                    answer="fixed rel",
                    nodes=[
                        {"source_id": "SOURCE_1", "role": "context"},
                        {"source_id": "SOURCE_2", "role": "supporting"},
                    ],
                    relationships=[{"from": "SOURCE_1", "to": "SOURCE_2", "type": "supports"}],
                ),
            )

        result = _gemini(handler).generate("q", _context(2))
        assert result.answer == "fixed rel"
        assert calls["n"] == 2
        assert "Correction:" in payloads[1]["contents"][0]["parts"][0]["text"]
        assert "Valid sources are: SOURCE_1, SOURCE_2" in payloads[1]["contents"][0]["parts"][
            0
        ]["text"]

    def test_hallucinated_to_triggers_retry(self) -> None:
        payloads: list[dict] = []
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            payloads.append(json.loads(request.content))
            if calls["n"] == 1:
                return httpx.Response(
                    200,
                    json=_reply(
                        answer="bad",
                        nodes=[{"source_id": "SOURCE_1", "role": "supporting"}],
                        relationships=[{"from": "SOURCE_1", "to": "SOURCE_99", "type": "supports"}],
                    ),
                )
            return httpx.Response(
                200,
                json=_reply(
                    answer="fixed",
                    nodes=[{"source_id": "SOURCE_1", "role": "supporting"}],
                ),
            )

        result = _gemini(handler).generate("q", _context(1))
        assert result.answer == "fixed"
        assert calls["n"] == 2
        assert "Valid sources are: SOURCE_1" in payloads[1]["contents"][0]["parts"][0]["text"]

    def test_hallucinated_source_fails_after_second_attempt(self) -> None:
        calls = {"n": 0}
        payloads: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            payloads.append(json.loads(request.content))
            return httpx.Response(
                200,
                json=_reply(
                    answer="still bad",
                    nodes=[{"source_id": "SOURCE_99", "role": "supporting"}],
                ),
            )

        with pytest.raises(InvalidCitationError, match="SOURCE_99"):
            _gemini(handler).generate("q", _context(1))
        assert calls["n"] == 2
        assert "Correction:" in payloads[1]["contents"][0]["parts"][0]["text"]
        assert "Valid sources are: SOURCE_1" in payloads[1]["contents"][0]["parts"][0]["text"]
        # also verify InvalidCitationError is subclass of GeneratorError
        try:
            _gemini(lambda req: httpx.Response(200, json=_reply(answer="x", nodes=[{"source_id": "SOURCE_99", "role": "supporting"}]))).generate("q", _context(1))
        except GeneratorError as exc:
            assert isinstance(exc, InvalidCitationError)

    def test_hallucinated_relationship_fails_after_retry(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(
                200,
                json=_reply(
                    answer="bad",
                    nodes=[{"source_id": "SOURCE_1", "role": "supporting"}],
                    relationships=[{"from": "SOURCE_1", "to": "SOURCE_99", "type": "supports"}],
                ),
            )

        with pytest.raises(InvalidCitationError):
            _gemini(handler).generate("q", _context(1))
        assert calls["n"] == 2

    def test_missing_api_key_fails_loud_at_startup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            monkeypatch.delenv(name, raising=False)
        with pytest.raises(GeneratorError, match="GEMINI_API_KEY"):
            GeminiGenerator()


class TestFactory:
    def test_default_provider_is_gemini(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        generator = create_generator()
        assert isinstance(generator, GeminiGenerator)
        assert generator._model == "gemini-2.5-flash"

    def test_provider_env_selects_mock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "mock")
        assert isinstance(create_generator(), MockGenerator)

    def test_model_env_selects_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.setenv("LLM_MODEL", "gemini-9.9-flash")
        generator = create_generator()
        assert isinstance(generator, GeminiGenerator)
        assert generator._model == "gemini-9.9-flash"

    def test_explicit_arguments_beat_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "gemini")
        assert isinstance(create_generator(provider="mock"), MockGenerator)

    def test_unknown_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown LLM_PROVIDER"):
            create_generator(provider="gpt")

    def test_factory_gemini_is_generator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "gemini")
        # ensure key exists for construction
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        gen = create_generator(provider="gemini", model="gemini-2.5-flash")
        assert isinstance(gen, Generator)
        assert isinstance(gen, GeminiGenerator)

    def test_factory_mock_is_generator(self) -> None:
        gen = create_generator(provider="mock")
        assert isinstance(gen, Generator)
        assert isinstance(gen, MockGenerator)


class _FakeRetriever:
    """Retriever stand-in returning fixed hits and recording calls."""

    def __init__(self, hits: list[dict]) -> None:
        self._hits = hits
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, top_k: int) -> dict:
        self.calls.append((query, top_k))
        return {"query": query, "top_k": top_k, "hits": self._hits}


class TestPipelineIntegration:
    def test_end_to_end_with_mock_generator(self) -> None:
        retriever = _FakeRetriever([_result("chunk_381"), _result("chunk_419")])
        pipeline = AnswerPipeline(
            retriever=retriever,
            generator=MockGenerator(reply="mock answer"),
        )
        result = pipeline.answer("why the drops?")
        assert isinstance(result, (EvidenceResult, TrailReport))
        assert result.answer == "mock answer"
        assert retriever.calls == [("why the drops?", 5)]

    def test_end_to_end_with_structured_mock_graph(self) -> None:
        nodes = [{"source_id": "SOURCE_1", "role": "supporting"}]
        structured = EvidenceResult(answer="structured text of chunk_381", nodes=nodes, relationships=[])  # type: ignore[arg-type]
        retriever = _FakeRetriever([_result("chunk_381")])
        pipeline = AnswerPipeline(retriever=retriever, generator=MockGenerator(reply=structured))
        result = pipeline.answer("q?")
        assert isinstance(result, (EvidenceResult, TrailReport))
        assert _unwrap(result).answer == "structured text of chunk_381"
        assert _unwrap(result).nodes[0].source_id == "SOURCE_1"

    def test_generator_is_swappable_without_pipeline_changes(self) -> None:
        retriever_a = _FakeRetriever([_result("chunk_381")])
        retriever_b = _FakeRetriever([_result("chunk_381")])
        mock_reply = EvidenceResult(answer="from mock text of chunk_381", nodes=[{"source_id": "SOURCE_1", "role": "supporting"}], relationships=[])  # type: ignore[arg-type]
        mock_pipeline = AnswerPipeline(
            retriever=retriever_a,
            generator=MockGenerator(reply=mock_reply),
        )
        gemini_pipeline = AnswerPipeline(
            retriever=retriever_b,
            generator=_gemini(lambda request: httpx.Response(200, json=_reply("from gemini text of chunk_381", nodes=[{"source_id": "SOURCE_1", "role": "supporting"}]))),
        )
        mock_result = mock_pipeline.answer("q?")
        gemini_result = gemini_pipeline.answer("q?")
        assert isinstance(mock_result, (EvidenceResult, TrailReport))
        assert isinstance(gemini_result, (EvidenceResult, TrailReport))
        assert _unwrap(mock_result).answer == "from mock text of chunk_381"
        assert _unwrap(gemini_result).answer == "from gemini text of chunk_381"

    def test_context_flows_through_intact(self) -> None:
        captured: list = []

        class SpyGenerator(MockGenerator):
            def generate(self, query, context):
                captured.append(context)
                return super().generate(query, context)

        retriever = _FakeRetriever([_result(f"chunk_{i}") for i in range(8)])
        pipeline = AnswerPipeline(retriever=retriever, generator=SpyGenerator())
        result = pipeline.answer("q?")
        assert isinstance(result, (EvidenceResult, TrailReport))
        context = captured[0]
        assert [s.chunk_id for s in context.sources] == [f"chunk_{i}" for i in range(5)]
        assert set(context.originals) == {f"SOURCE_{i}" for i in range(1, 6)}

    def test_pipeline_answer_returns_evidence_result_for_gemini(self) -> None:
        retriever = _FakeRetriever([_result("chunk_381"), _result("chunk_419")])
        nodes = [
            {"source_id": "SOURCE_1", "role": "context"},
            {"source_id": "SOURCE_2", "role": "supporting"},
        ]
        relationships = [{"from": "SOURCE_1", "to": "SOURCE_2", "type": "supports"}]
        gemini = _gemini(
            lambda request: httpx.Response(
                200, json=_reply(answer="gemini structured", nodes=nodes, relationships=relationships)
            )
        )
        pipeline = AnswerPipeline(retriever=retriever, generator=gemini)
        result = pipeline.answer("explain?")
        assert isinstance(result, (EvidenceResult, TrailReport))
        assert result.answer == "gemini structured"
        assert len(result.nodes) == 2
        assert len(result.relationships) == 1
        assert result.relationships[0].type == "supports"
