"""Locate snippet bounding rectangles on PDF pages via PyMuPDF.

Two localization strategies live here:

- :func:`locate_text` — whole-snippet search via ``Page.search_for``;
  yields line-width rectangles (the previous, coarse approach).
- :func:`locate_words` — per-word spans via ``Page.get_text("words")``;
  matches the snippet's tokens against them in reading order and emits
  one tight rectangle per matched word (the precise approach).

Both share the same coordinate system and page-range guard: out-of-range
pages yield ``[]`` and genuine errors (e.g. corrupt PDF bytes) are left
to the caller. Block-extracted text contains newlines and irregular
whitespace, so snippets are tokenized on whitespace rather than matched
verbatim.
"""

from __future__ import annotations

import re
import unicodedata

import pymupdf

_FALLBACK_LENGTH = 80

#: Minimum share of snippet tokens that must land in the best matched run
#: before word rects are trusted; below this, callers should fall back to
#: :func:`locate_text`.
_MIN_TOKEN_MATCH = 0.6

#: Words are whitespace-separated; punctuation stays attached to its word.
_WORD_SPLIT = re.compile(r"\S+")

#: Everything except letters and digits is stripped from match keys, so
#: ``(INT8,`` compares equal to ``int8`` and ``18.48`` to ``1848``.
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def locate_text(
    pdf_bytes: bytes,
    page_number: int,
    snippet: str,
) -> list[tuple[float, float, float, float]]:
    """Find exact bounding rectangles for snippet on the given page.

    Page numbers are 1-based, matching the :class:`Chunk` model. If the
    snippet cannot be found, its first :data:`_FALLBACK_LENGTH`
    characters are retried in case the snippet outgrew its source text.

    :param pdf_bytes: PDF file contents.
    :param page_number: 1-based page number.
    :param snippet: text to locate on the page.
    :return: ``(x0, y0, x1, y1)`` rectangles for every match, or ``[]``.
    """
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        if page_number < 1 or page_number > doc.page_count:
            return []
        page = doc[page_number - 1]
        text = re.sub(r"\s+", " ", snippet).strip()
        rects = page.search_for(text)
        if not rects:
            rects = page.search_for(text[:_FALLBACK_LENGTH])
        return [(r.x0, r.y0, r.x1, r.y1) for r in rects]


def _word_key(text: str) -> str:
    """Normalize *text* into a comparable token key.

    Applies NFKC folding (so ligatures like ``ﬁ`` collapse to ``fi``),
    lowercases, and strips everything that is not a letter or digit.
    """
    folded = unicodedata.normalize("NFKC", text)
    return _NON_ALNUM.sub("", folded.lower())


def _matched_span(
    token_key: str,
    page_words: list[tuple[str, str, tuple[float, float, float, float]]],
    j: int,
) -> int | None:
    """Number of page words at ``page_words[j]`` that form *token_key*.

    Returns ``None`` when the token matches nothing there. Two tolerances
    apply, tried longest-span first:

    1. **Fragment join**: when the first word ends with a hyphen (a
       line-break split), its key is joined with the following words'
       keys until the concatenation rebuilds the token — ``chunk-`` +
       ``ing`` forms ``chunking`` and consumes two words.
    2. **Single word**: exact key equality, or a hyphen-terminated word
       whose key prefixes the token (e.g. PDF ``chunk-`` for token
       ``chunky``).
    """
    word_key, raw_word, _rect = page_words[j]
    if raw_word.endswith("-"):
        joined = word_key
        k = j + 1
        while k < len(page_words):
            joined += page_words[k][0]
            k += 1
            if joined == token_key:
                return k - j
            if len(joined) > len(token_key):
                break
    if token_key == word_key:
        return 1
    if bool(word_key) and raw_word.endswith("-") and token_key.startswith(word_key):
        return 1
    return None


def locate_words(
    pdf_bytes: bytes,
    page_number: int,
    snippet: str,
) -> list[tuple[float, float, float, float]]:
    """Find tight per-word rectangles for *snippet* on the given page.

    The snippet is tokenized on whitespace and each token is matched
    against the page's word spans (``Page.get_text("words")``) in reading
    order. The **longest consecutive run** of matched tokens decides the
    highlight: one rectangle per matched word, so a run crossing a line
    break yields separate rects per line.

    Runs that cover fewer than ``_MIN_TOKEN_MATCH`` of the snippet's
    tokens are rejected (``[]``) so the caller can fall back to
    :func:`locate_text`.

    :param pdf_bytes: PDF file contents.
    :param page_number: 1-based page number.
    :param snippet: text to locate on the page.
    :return: ``(x0, y0, x1, y1)`` rectangles per matched word, or ``[]``.
    """
    snippet_tokens = [w for w in _WORD_SPLIT.findall(snippet)]
    tokens = [_word_key(t) for t in snippet_tokens if _word_key(t)]
    if not tokens:
        return []

    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        if page_number < 1 or page_number > doc.page_count:
            return []
        page = doc[page_number - 1]
        word_spans = page.get_text("words", sort=True)

    page_words: list[tuple[str, str, tuple[float, float, float, float]]] = []
    for x0, y0, x1, y1, raw, _block, _line, _word_no in word_spans:
        key = _word_key(raw)
        if key:
            page_words.append((key, raw, (x0, y0, x1, y1)))

    best_tokens = 0
    best_rects: list[tuple[float, float, float, float]] = []
    for i, token_key in enumerate(tokens):
        for j in range(len(page_words)):
            span = _matched_span(token_key, page_words, j)
            if span is None:
                continue
            rects = [page_words[j + r][2] for r in range(span)]
            matched = 1
            word_pos = j + span
            while i + matched < len(tokens) and word_pos < len(page_words):
                next_span = _matched_span(tokens[i + matched], page_words, word_pos)
                if next_span is None:
                    break
                rects.extend(page_words[word_pos + r][2] for r in range(next_span))
                matched += 1
                word_pos += next_span
            if matched > best_tokens:
                best_tokens = matched
                best_rects = rects

    if best_tokens == 0 or best_tokens / len(tokens) < _MIN_TOKEN_MATCH:
        return []
    return best_rects
