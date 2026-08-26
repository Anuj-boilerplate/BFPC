"""Gemini-backed Generator: the only Gemini-specific code in BFPC.

Owns everything Gemini: client construction (once, at startup), model
selection, ``generateContent`` request assembly, response extraction and
API error handling with retry on transient failures. Nothing else in the
codebase may import this module — consumers go through
:class:`bfpc.context.base.Generator` via
:func:`bfpc.context.factory.create_generator`.

Configuration precedence (constructor argument wins over environment):
``LLM_MODEL`` selects the model; the API key comes from
``GEMINI_API_KEY`` (``GOOGLE_API_KEY`` accepted as fallback).
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Sequence

import httpx
from pydantic import ValidationError

from bfpc.context.base import Generator, GeneratorError, InvalidCitationError
from bfpc.context.builder import LLMContext
from bfpc.context.completeness import CompletenessReport, TrailReport
from bfpc.context.evidence import Claim, EvidenceResult

#: Environment variables that may carry the Gemini API key.
_API_KEY_ENVS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")

#: Default model when neither constructor nor ``LLM_MODEL`` says otherwise.
DEFAULT_MODEL = "gemini-3.6-flash"

#: Default API root; overridable for tests / proxies.
DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

#: Backoff schedule (seconds) for rate limits and transient server errors.
RETRY_DELAYS: tuple[float, ...] = (1.0, 2.0, 4.0)

_SYSTEM_INSTRUCTION = (
    "You answer questions strictly using the numbered source excerpts "
    "provided by the user. Follow these rules exactly: "
    "(1) Answer using only the supplied passages. "
    "(2) Select ONLY the passages necessary for the answer — omit "
    "irrelevant ones; do not list every source as a node. "
    "(3) Assign each selected source an appropriate role: context, "
    "supporting, definition, example, or conclusion. "
    "(4) Describe how selected sources relate using one type per pair: "
    "supports, explains, defines, qualifies, contrasts, or follows_from. "
    "(5) Never invent source ids — every source_id/from/to must be one of "
    "the SOURCE_N ids supplied in the prompt. "
    "(6) Assess sufficiency: set status to SUFFICIENT when the supplied "
    "passages contain everything needed to answer, otherwise INSUFFICIENT "
    "and describe in 'missing' which evidence is absent (plain text — "
    "never attach a source id to it). If the excerpts do not contain the "
    "answer, say that you don't know and mark it INSUFFICIENT. "
    "(7) For each distinct assertion in your answer emit a claim object "
    "with: id (C1, C2…), text (the assertion), required (true if the "
    "answer is incomplete without it), evidence_ids (list of SOURCE_N that "
    "directly support it), depends_on (list of other claim ids this builds "
    "on). Omit claims for filler/acknowledgement sentences."
)

_RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "status": {"type": "string", "enum": ["SUFFICIENT", "INSUFFICIENT"]},
        "missing": {"type": "string"},
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_id": {"type": "string"},
                    "role": {
                        "type": "string",
                        "enum": [
                            "context",
                            "supporting",
                            "definition",
                            "example",
                            "conclusion",
                        ],
                    },
                },
                "required": ["source_id", "role"],
            },
        },
        "relationships": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": [
                            "supports",
                            "explains",
                            "defines",
                            "qualifies",
                            "contrasts",
                            "follows_from",
                        ],
                    },
                },
                "required": ["from", "to", "type"],
            },
        },
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                    "required": {"type": "boolean"},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "text", "required"],
            },
        },
    },
    "required": ["answer", "status", "nodes", "relationships"],
}


def _api_key() -> str:
    for name in _API_KEY_ENVS:
        key = os.environ.get(name)
        if key:
            return key
    raise GeneratorError("no Gemini API key found; set GEMINI_API_KEY")


class GeminiGenerator(Generator):
    """Generates structured evidence via the Gemini API ``generateContent``."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = 120.0,
        temperature: float = 0.2,
        retry_delays: Sequence[float] = RETRY_DELAYS,
    ) -> None:
        """:param model: Gemini model name (e.g. ``gemini-3.6-flash``).
        :param base_url: API root; override for tests or proxies.
        :param api_key: defaults to the ``GEMINI_API_KEY`` env var.
        :param client: pre-built httpx client (tests); one is created otherwise.
        :param timeout: per-request timeout in seconds.
        :param temperature: sampling temperature for ``generationConfig``.
        :param retry_delays: backoff schedule between transient-failure retries.

        The client is built here once — at application startup — and reused
        for every query.
        """
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key if api_key is not None else _api_key()
        self._client = client if client is not None else httpx.Client(timeout=timeout)
        self._owns_client = client is None
        self._temperature = temperature
        self._retry_delays = tuple(retry_delays)

    def close(self) -> None:
        """Release the underlying HTTP client (only if we created it)."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> GeminiGenerator:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def generate(self, query: str, context: LLMContext) -> TrailReport:
        """Ask Gemini and return validated structured evidence."""
        try:
            return self._generate_once(query, context, correction=None)
        except InvalidCitationError as exc:
            # Single retry with a correction that lists the valid ids.
            valid = ", ".join(sorted(context.originals.keys())) or "(no sources)"
            correction = f"{exc} Valid sources are: {valid}. Retry using only those."
            return self._generate_once(query, context, correction=correction)

    def _generate_once(
        self, query: str, context: LLMContext, correction: str | None
    ) -> TrailReport:
        data = self._post(self._payload(query, context, correction))
        raw_text = self._extract_text(data)
        return self._parse_and_validate(raw_text, context)

    # -- request assembly --------------------------------------------------

    def _payload(self, query: str, context: LLMContext, correction: str | None) -> dict:
        sources_block = "\n\n".join(
            f"[{source.source_id}] (page {source.page}, {source.kind})\n{source.text}"
            for source in context.sources
        )
        user_text = f"Sources:\n{sources_block}\n\nQuestion: {query}"
        if correction is not None:
            user_text += f"\n\nCorrection: {correction}"
        return {
            "systemInstruction": {"parts": [{"text": _SYSTEM_INSTRUCTION}]},
            "contents": [{"role": "user", "parts": [{"text": user_text}]}],
            "generationConfig": {
                "temperature": self._temperature,
                "responseMimeType": "application/json",
                "responseSchema": _RESPONSE_SCHEMA,
            },
        }

    # -- transport ---------------------------------------------------------

    def _post(self, payload: dict) -> dict:
        url = f"{self._base_url}/models/{self._model}:generateContent"
        headers = {"x-goog-api-key": self._api_key}
        max_attempts = len(self._retry_delays) + 1
        last_error = "Gemini generateContent failed"
        for attempt in range(max_attempts):
            try:
                response = self._client.post(url, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                last_error = f"Gemini request failed: {exc}"
                if attempt == max_attempts - 1:
                    break
                time.sleep(self._retry_delays[attempt])
                continue
            if response.status_code == 200:
                return response.json()
            last_error = f"Gemini error {response.status_code}: {response.text[:300]}"
            if response.status_code not in (429, 500, 502, 503, 504):
                break
            if attempt < max_attempts - 1:
                time.sleep(self._retry_delays[attempt])
        raise GeneratorError(last_error)

    # -- response extraction -------------------------------------------------

    @staticmethod
    def _extract_text(data: dict) -> str:
        feedback = data.get("promptFeedback") or {}
        if feedback.get("blockReason"):
            raise GeneratorError(f"prompt blocked: {feedback['blockReason']}")
        candidates = data.get("candidates") or []
        if not candidates:
            raise GeneratorError("response contained no candidates")
        first = candidates[0]
        parts = ((first.get("content") or {}).get("parts")) or []
        text = "".join(part.get("text", "") for part in parts).strip()
        if not text:
            finish_reason = first.get("finishReason", "unknown")
            raise GeneratorError(f"empty completion (finishReason={finish_reason})")
        return text

    # Kept for backwards-compat in tests that call _extract directly.
    @staticmethod
    def _extract(data: dict) -> str:
        return GeminiGenerator._extract_text(data)

    def _parse_and_validate(self, raw_text: str, context: LLMContext) -> TrailReport:
        # Strip markdown fences like ```json ... ``` if present.
        text = raw_text.strip()
        fence = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", text, re.DOTALL)
        if fence is not None:
            text = fence.group(1).strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise GeneratorError(f"invalid JSON from LLM: {exc}") from exc

        # Extract claims before handing rest to EvidenceResult (which is extra="forbid").
        claims: list[Claim] = []
        if isinstance(payload, dict) and "claims" in payload:
            raw_claims = payload.pop("claims")
            if raw_claims is not None:
                if not isinstance(raw_claims, list):
                    raise GeneratorError("invalid claims shape: not a list")
                for raw in raw_claims:
                    try:
                        claims.append(Claim.model_validate(raw))
                    except ValidationError as exc:
                        raise GeneratorError(f"invalid claim shape: {exc}") from exc

        # Hallucination check before Pydantic graph validation: the LLM may
        # emit a relationship whose endpoint was never supplied (e.g. from
        # "SOURCE_99"). EvidenceResult's model_validator would reject this
        # as "no matching node" -> ValidationError -> GeneratorError, which
        # would NOT trigger the single citation retry. Catch it early as
        # InvalidCitationError so the retry path is hit.
        valid_ids = set(context.originals.keys())
        if isinstance(payload, dict):
            for node in payload.get("nodes") or []:
                if isinstance(node, dict):
                    sid = node.get("source_id")
                    if isinstance(sid, str) and sid not in valid_ids:
                        raise InvalidCitationError(
                            f"unknown source '{sid}' — not in context"
                        )
            for rel in payload.get("relationships") or []:
                if isinstance(rel, dict):
                    fid = rel.get("from")
                    tid = rel.get("to")
                    if isinstance(fid, str) and fid not in valid_ids:
                        raise InvalidCitationError(
                            f"relationship from '{fid}' not in context"
                        )
                    if isinstance(tid, str) and tid not in valid_ids:
                        raise InvalidCitationError(
                            f"relationship to '{tid}' not in context"
                        )
            # Also check claims evidence_ids for hallucinated sources
            for claim in claims:
                for eid in claim.evidence_ids:
                    if eid not in valid_ids:
                        raise InvalidCitationError(
                            f"unknown source '{eid}' in claim '{claim.id}' — not in context"
                        )

        try:
            result = EvidenceResult.model_validate(payload)
        except ValidationError as exc:
            raise GeneratorError(f"invalid evidence shape: {exc}") from exc

        for node in result.nodes:
            if node.source_id not in valid_ids:
                raise InvalidCitationError(
                    f"unknown source '{node.source_id}' — not in context"
                )
        for rel in result.relationships:
            if rel.from_id not in valid_ids:
                raise InvalidCitationError(
                    f"relationship from '{rel.from_id}' not in context"
                )
            if rel.to not in valid_ids:
                raise InvalidCitationError(
                    f"relationship to '{rel.to}' not in context"
                )
        for claim in claims:
            for eid in claim.evidence_ids:
                if eid not in valid_ids:
                    raise InvalidCitationError(
                        f"unknown source '{eid}' in claim '{claim.id}' — not in context"
                    )

        # Generator returns a TrailReport; the checker will recompute the
        # definitive report in the pipeline, but we provide a placeholder
        # passing report here so callers always get a TrailReport.
        placeholder = CompletenessReport(
            complete=True, reasons=[], uncovered_claims=[], unresolved_deps=[]
        )
        return TrailReport(result=result, claims=claims, report=placeholder)
