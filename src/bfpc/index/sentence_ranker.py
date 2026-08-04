"""Sentence-level relevance ranking for retrieval.

Ranks the sentences of a chunk against a user query using Jaccard
word-overlap similarity: both texts are lowercased and tokenized into
word sets via ``\\w+``, and the score is ``|intersection| / |union|``
(0.0 when the union is empty). Pure standard library, so it needs no
models or dependencies and can serve as a cheap pre-filter before any
embedding-based search.
"""

from __future__ import annotations

import re

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def rank_sentences(query: str, text: str, top_n: int = 1) -> list[str]:
    """Return the top_n sentences from text most relevant to query.

    Sentences are split on ``.``, ``!``, or ``?`` when followed by
    whitespace (so a sentence ending right before a newline still splits,
    while a decimal point like ``18.48`` does not). Each sentence is
    scored by Jaccard word-overlap with the query, and the best ``top_n``
    are returned in descending order with ties broken by original order.
    Blank text yields ``[]``; when no sentence overlaps the query at all,
    the full stripped text is returned as a fallback.

    :param query: The user's search query used to score sentences.
    :param text: Chunk text to split into and rank sentences from.
    :param top_n: Maximum number of sentences to return.
    :return: The top_n most relevant sentences, best first.
    """
    stripped = text.strip()
    if not stripped or top_n <= 0:
        return []
    sentences = [piece.strip() for piece in _SENTENCE_SPLIT.split(stripped) if piece.strip()]
    query_tokens = set(re.findall(r"\w+", query.lower()))
    scored = []
    for sentence in sentences:
        sentence_tokens = set(re.findall(r"\w+", sentence.lower()))
        if not query_tokens or not sentence_tokens:
            score = 0.0
        else:
            score = len(query_tokens & sentence_tokens) / len(query_tokens | sentence_tokens)
        scored.append((score, sentence))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    if scored[0][0] == 0.0:
        return [stripped]
    return [sentence for _, sentence in scored[:top_n]]