"""Embedding layer wrapping the nomic-embed-text-v1.5 model.

The model was trained with instruction prefixes: queries get a
``search_query:`` prefix and documents a ``search_document:`` prefix.
Loading is lazy on first use and cached for the process lifetime, so
the CLI stays fast and the ~274 MB model downloads exactly once.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence

import numpy as np

MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"
QUERY_PREFIX = "search_query: "
DOCUMENT_PREFIX = "search_document: "


class Embedder:
    """Thin, prefix-aware wrapper over sentence-transformers."""

    def __init__(self, model_name: str = MODEL_NAME) -> None:
        self._model_name = model_name
        self._model = None
        # Model inference is not safe to run concurrently from multiple
        # threads (an index swap and a search can overlap); serialize it.
        self._encode_lock = threading.Lock()

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        """Embed document texts; returns a (n, dim) float32 array, L2-normalized."""
        return self._encode([DOCUMENT_PREFIX + text for text in texts])

    def embed_query(self, query: str) -> np.ndarray:
        """Embed a search query; returns a (dim,) float32 vector, L2-normalized."""
        return self._encode([QUERY_PREFIX + query])[0]

    def _encode(self, texts: list[str]) -> np.ndarray:
        with self._encode_lock:
            if self._model is None:
                self._model = self._load()
            vectors = self._model.encode(
                texts,
                normalize_embeddings=True,
                batch_size=64,
                show_progress_bar=False,
            )
        return np.asarray(vectors, dtype=np.float32)

    def _load(self):
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(self._model_name)
