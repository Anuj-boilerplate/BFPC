"""Embedding layer backed by the Google Gemini embedding API.

Uses ``gemini-embedding-001`` at the full 3072 dimensions (lower dims are
Matryoshka truncations). Documents are embedded with
``taskType=RETRIEVAL_DOCUMENT`` and queries with ``RETRIEVAL_QUERY`` —
Gemini's replacement for the instruction prefixes nomic-embed-text used.
Configuration comes from the environment:

- ``GEMINI_API_KEY``       (required; ``GOOGLE_API_KEY`` accepted as a fallback)
- ``BFPC_EMBED_MODEL``     (default ``gemini-embedding-001``)
- ``BFPC_EMBED_BASE_URL``  (default ``https://generativelanguage.googleapis.com/v1beta``)
- ``BFPC_EMBED_BATCH_DELAY`` (seconds to sleep between batches; default ``0.65``)

The client is pure HTTP (``httpx``): no local model, no download, no
torch. Up to ``MAX_BATCH`` texts go in one ``:batchEmbedContents`` call;
transient failures retry with backoff. A configurable inter-batch delay
keeps multi-batch index calls comfortably under the 100 RPM free-tier
limit. On 429 responses the ``Retry-After`` header is respected when
present so retries don't fire too early.
"""

from __future__ import annotations

import os
import time
from collections.abc import Sequence

import httpx
import numpy as np

#: Environment variables that may carry the Gemini API key, in priority order.
_API_KEY_ENVS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")

MODEL_NAME = os.environ.get("BFPC_EMBED_MODEL", "gemini-embedding-001")
BASE_URL = os.environ.get(
    "BFPC_EMBED_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
)

#: Full embedding dimensionality of gemini-embedding-001.
OUTPUT_DIMENSIONALITY = 3072

#: Max content parts per :batchEmbedContents call (API limit).
MAX_BATCH = 100

#: Seconds to sleep between successive batches during a single embed_documents
#: call.  Keeps free-tier (100 RPM) users well clear of the rate limit without
#: adding latency for single-batch documents.  Override with
#: ``BFPC_EMBED_BATCH_DELAY=0`` to disable.
INTER_BATCH_DELAY: float = float(os.environ.get("BFPC_EMBED_BATCH_DELAY", "0.65"))

#: Backoff schedule (seconds) for rate limits and transient server errors.
#: Used only when no ``Retry-After`` header is present on a 429 response.
RETRY_DELAYS = (1.0, 2.0, 4.0)


def _api_key() -> str:
    for name in _API_KEY_ENVS:
        key = os.environ.get(name)
        if key:
            return key
    raise RuntimeError("no Gemini API key found; set GEMINI_API_KEY")


class Embedder:
    """Thin wrapper over the Gemini embedding API (embeddings are L2-normalized)."""

    def __init__(
        self,
        model_name: str = MODEL_NAME,
        base_url: str = BASE_URL,
        api_key: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._model_name = model_name
        self._base_url = base_url
        self._api_key = api_key if api_key is not None else _api_key()
        self._client = client or httpx.Client(timeout=120)

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        """Embed document texts; returns a (n, 3072) float32 array, L2-normalized."""
        return self._encode(list(texts), task_type="RETRIEVAL_DOCUMENT")

    def embed_query(self, query: str) -> np.ndarray:
        """Embed a search query; returns a (3072,) float32 vector, L2-normalized."""
        return self._encode([query], task_type="RETRIEVAL_QUERY")[0]

    def _encode(self, texts: list[str], task_type: str) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        vectors: list[np.ndarray] = []
        for start in range(0, len(texts), MAX_BATCH):
            # Sleep between batches to stay within the 100 RPM free-tier limit.
            # The first batch never waits; subsequent batches pause for
            # INTER_BATCH_DELAY seconds (default 0.65 s, ~92 RPM headroom).
            if start > 0 and INTER_BATCH_DELAY > 0:
                time.sleep(INTER_BATCH_DELAY)
            batch = texts[start : start + MAX_BATCH]
            payload = {
                "requests": [
                    {
                        "model": f"models/{self._model_name}",
                        "content": {"parts": [{"text": text}]},
                        "taskType": task_type,
                        "outputDimensionality": OUTPUT_DIMENSIONALITY,
                    }
                    for text in batch
                ]
            }
            data = self._post(f"/models/{self._model_name}:batchEmbedContents", payload)
            for embedding in data["embeddings"]:
                vectors.append(np.asarray(embedding["values"], dtype=np.float32))
        matrix = np.stack(vectors, axis=0)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        return matrix / np.where(norms == 0, 1.0, norms)

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self._base_url.rstrip('/')}{path}"
        headers = {"x-goog-api-key": self._api_key}
        for attempt, delay in enumerate(RETRY_DELAYS):
            try:
                response = self._client.post(url, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                if attempt == len(RETRY_DELAYS) - 1:
                    raise RuntimeError(f"Gemini embedding request failed: {exc}") from exc
                time.sleep(delay)
                continue
            if response.status_code == 200:
                return response.json()
            if response.status_code in (429, 500, 502, 503, 504):
                if attempt < len(RETRY_DELAYS) - 1:
                    # Honour the API's own cooldown instruction when present;
                    # fall back to the fixed backoff schedule otherwise.
                    retry_after = response.headers.get("Retry-After")
                    wait = float(retry_after) if retry_after is not None else delay
                    time.sleep(wait)
                    continue
            raise RuntimeError(
                f"Gemini embedding API error {response.status_code}: {response.text[:300]}"
            )
        raise RuntimeError("Gemini embedding API unreachable")  # pragma: no cover