"""Configuration-driven selection of the Generator implementation.

Reads ``LLM_PROVIDER`` (default ``gemini``) and ``LLM_MODEL``, so the
application never hardcodes a provider: switching BFPC to another model
or to the offline mock is an environment change, not a code change.
Call :func:`create_generator` once at application startup and reuse the
returned instance for every query.
"""

from __future__ import annotations

import os

from bfpc.context.base import Generator
from bfpc.context.gemini_generator import GeminiGenerator
from bfpc.context.mock_generator import MockGenerator

#: Environment variable choosing the implementation.
PROVIDER_ENV = "LLM_PROVIDER"

#: Environment variable choosing the model (Gemini only).
MODEL_ENV = "LLM_MODEL"

#: Providers understood by :func:`create_generator`.
PROVIDERS: tuple[str, ...] = ("gemini", "mock")


def create_generator(
    provider: str | None = None,
    model: str | None = None,
) -> Generator:
    """Build the configured generator (call once at startup, reuse forever).

    :param provider: ``"gemini"`` or ``"mock"``; defaults to the
        ``LLM_PROVIDER`` env var, then ``"gemini"``.
    :param model: model name for Gemini; defaults to the ``LLM_MODEL``
        env var, then the GeminiGenerator default. Ignored by the mock.
    :raises ValueError: when the resolved provider is unknown.
    """
    resolved = (provider if provider is not None else os.environ.get(PROVIDER_ENV) or "gemini")
    resolved = resolved.strip().lower()
    if resolved == "gemini":
        chosen_model = model if model is not None else os.environ.get(MODEL_ENV) or None
        return GeminiGenerator(model=chosen_model) if chosen_model else GeminiGenerator()
    if resolved == "mock":
        return MockGenerator()
    raise ValueError(
        f"unknown LLM_PROVIDER '{resolved}'; expected one of: {', '.join(PROVIDERS)}"
    )
