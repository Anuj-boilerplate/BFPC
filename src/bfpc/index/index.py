"""FAISS-backed vector index for exact cosine retrieval.

FAISS identifiers are positional: index id ``i`` maps to the chunk at
``self._chunks[i]``. Vectors are expected L2-normalized, so inner
product equals cosine similarity.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from bfpc.index.chunker import Chunk


@dataclass(frozen=True, slots=True)
class Hit:
    """One retrieval result: the chunk and its cosine similarity score."""

    chunk: Chunk
    score: float


#: Optional-priority for equal-score ties. Prefer content-bearing chunks
#: (TEXT/TABLE) over structural ones (LIST/HEADING) so the "right topic
#: page" surfaces at rank 1. Unknown kinds default to the highest priority.
_KIND_RANK: dict[str, int] = {
    "text": 0,
    "table": 0,
    "list": 1,
    "heading": 1,
}


class VectorIndex:
    """Exact inner-product (cosine) index over normalized embeddings.

    ``faiss`` is imported lazily so importing this module stays cheap
    for CLI entry points that never touch the vector path.
    """

    def __init__(self) -> None:
        self._chunks: list[Chunk] = []
        self._index = None

    def __len__(self) -> int:
        return len(self._chunks)

    def add(self, chunks: Sequence[Chunk], vectors: np.ndarray) -> None:
        """Add chunks paired with their embedding vectors."""
        if len(chunks) != vectors.shape[0]:
            raise ValueError(
                f"got {len(chunks)} chunks but {vectors.shape[0]} vectors"
            )
        if not chunks:
            return
        import faiss

        if self._index is None:
            self._index = faiss.IndexFlatIP(int(vectors.shape[1]))
        self._index.add(np.asarray(vectors, dtype=np.float32))
        self._chunks.extend(chunks)

    def search(self, query_vector: np.ndarray, k: int = 5) -> list[Hit]:
        """Return the ``k`` nearest chunks, best first.

        :raises ValueError: if the index is empty or ``k`` is not positive.
        """
        if self._index is None or self._index.ntotal == 0:
            raise ValueError("index is empty; add chunks before searching")
        if k < 1:
            raise ValueError(f"k must be >= 1, got {k}")
        import faiss

        k = min(k, self._index.ntotal)
        scores, ids = self._index.search(
            np.asarray(query_vector, dtype=np.float32).reshape(1, -1), k
        )
        hits = [
            Hit(chunk=self._chunks[i], score=float(score))
            for score, i in zip(scores[0], ids[0])
            if i >= 0
        ]
        # Ties (equal scores) are reordered to prefer TEXT/TABLE content.
        # Scores are compared with a tiny epsilon so near-equal floats from
        # FAISS are treated as ties without disturbing real rank order.
        tolerance = 1e-6
        hits.sort(
            key=lambda hit: (
                -round(hit.score / tolerance) * tolerance,
                _KIND_RANK.get(hit.chunk.kind, 0),
            )
        )
        return hits
