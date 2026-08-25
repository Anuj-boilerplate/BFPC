"""Unit tests for :func:`bfpc.index.locator.locate_text` / ``locate_words``.

A two-page PDF is generated on the fly, mirroring the fixture style of
tests/test_api.py: page 1 carries a title, page 2 carries the factoid
sentence plus a second line on a 200x200 page. Two PyMuPDF quirks shape
the fixture: glyphs written outside the page rectangle are invisible to
``search_for``, so the font is sized down until both lines fit; and the
needle must be an on-page prefix, so the sentence line ends with extra
words that give the module's 80-character fallback a deterministic match.
"""

from __future__ import annotations

import pymupdf
import pytest

from bfpc.index.locator import locate_text, locate_words

_PAGE_SIZE = 200
_TITLE = "Report title"
_SENTENCE = "INT8 static quantization latency is 18.48 ms."
_LINE_TWO = "FP16 runtime uses a CUDA backend."
_LINE_ONE = _SENTENCE + " Extra words here."


@pytest.fixture()
def pdf_bytes() -> bytes:
    """Two 200x200 pages: a title on page 1, two factoid lines on page 2."""
    doc = pymupdf.open()
    page = doc.new_page(width=_PAGE_SIZE, height=_PAGE_SIZE)
    page.insert_text((20, 40), _TITLE, fontsize=18)
    page = doc.new_page(width=_PAGE_SIZE, height=_PAGE_SIZE)
    page.insert_text((20, 80), _LINE_ONE, fontsize=6)
    page.insert_text((20, 120), _LINE_TWO, fontsize=6)
    buffer = doc.tobytes()
    doc.close()
    return buffer


@pytest.fixture()
def hyphen_pdf_bytes() -> bytes:
    """One page whose first line ends mid-word and the second starts it."""
    doc = pymupdf.open()
    page = doc.new_page(width=_PAGE_SIZE, height=_PAGE_SIZE)
    page.insert_text((20, 60), "chunk-", fontsize=10)
    page.insert_text((20, 100), "ing works fine", fontsize=10)
    buffer = doc.tobytes()
    doc.close()
    return buffer


@pytest.fixture()
def wrap_pdf_bytes() -> bytes:
    """One page whose first line ends with 'beta' and second starts 'gamma'."""
    doc = pymupdf.open()
    page = doc.new_page(width=_PAGE_SIZE, height=_PAGE_SIZE)
    page.insert_text((20, 60), "alpha beta", fontsize=10)
    page.insert_text((20, 100), "gamma delta", fontsize=10)
    buffer = doc.tobytes()
    doc.close()
    return buffer


class TestLocateText:
    def test_exact_sentence_found_on_page_2(self, pdf_bytes: bytes) -> None:
        rects = locate_text(pdf_bytes, 2, _SENTENCE)
        assert rects
        for rect in rects:
            assert len(rect) == 4
            assert all(isinstance(v, float) for v in rect)
            assert rect[0] <= rect[2]
            assert rect[1] <= rect[3]

    def test_page_number_is_one_based(self, pdf_bytes: bytes) -> None:
        # page 1 has no page-2 text, so nothing can come back for it.
        assert locate_text(pdf_bytes, 1, _SENTENCE) == []

    def test_longer_snippet_found_via_fallback(self, pdf_bytes: bytes) -> None:
        long_snippet = (
            _SENTENCE + " Extra words here. FP16 runtime use" + " padding words"
        )
        rects = locate_text(pdf_bytes, 2, long_snippet)
        # The full snippet is not on the page; the 80-character prefix is.
        assert rects
        assert any(60 <= rect[1] <= 95 for rect in rects)

    def test_unknown_text_returns_empty(self, pdf_bytes: bytes) -> None:
        assert locate_text(pdf_bytes, 2, "no such sentence exists here") == []

    def test_page_number_out_of_range_returns_empty(self, pdf_bytes: bytes) -> None:
        assert locate_text(pdf_bytes, 0, _SENTENCE) == []
        assert locate_text(pdf_bytes, 99, _SENTENCE) == []

    def test_rectangle_near_inserted_text_position(self, pdf_bytes: bytes) -> None:
        x0, y0, x1, y1 = locate_text(pdf_bytes, 2, _SENTENCE)[0]
        assert x0 >= 15


class TestLocateWords:
    def test_one_rect_per_matched_word(self, pdf_bytes: bytes) -> None:
        rects = locate_words(pdf_bytes, 2, "static quantization latency")
        assert len(rects) == 3
        for rect in rects:
            assert all(isinstance(v, float) for v in rect)
            assert rect[0] <= rect[2]
            assert rect[1] <= rect[3]

    def test_word_rects_tighter_than_sentence_box(self, pdf_bytes: bytes) -> None:
        word_rects = locate_words(pdf_bytes, 2, "latency is 18.48 ms.")
        assert word_rects
        sentence_box = locate_text(pdf_bytes, 2, _SENTENCE)[0]
        sentence_width = sentence_box[2] - sentence_box[0]
        for rect in word_rects:
            assert rect[2] - rect[0] < sentence_width

    def test_longest_consecutive_run_survives_noise(self, pdf_bytes: bytes) -> None:
        rects = locate_words(pdf_bytes, 2, "latency is 18.48 imaginary ms")
        # 'imaginary' is not on the page and splits the snippet, so the
        # longest consecutive run is "latency is 18.48" (3/5 tokens, above
        # the 0.6 threshold) — 'imaginary' and trailing 'ms' are dropped.
        assert len(rects) == 3

    def test_poor_match_returns_empty(self, pdf_bytes: bytes) -> None:
        assert locate_words(pdf_bytes, 2, "quantization imaginary mystery") == []

    def test_punctuation_is_tolerated(self, pdf_bytes: bytes) -> None:
        rects = locate_words(pdf_bytes, 2, "INT8,")
        assert len(rects) == 1

    def test_hyphenated_line_break_tolerated(self, hyphen_pdf_bytes: bytes) -> None:
        # "chunk-" + "ing" are two page words but one snippet token; both
        # rects come back so the highlight covers the whole split word.
        rects = locate_words(hyphen_pdf_bytes, 1, "chunking")
        assert len(rects) == 2
        rects = locate_words(hyphen_pdf_bytes, 1, "chunking works")
        assert len(rects) == 3

    def test_run_crossing_line_break_yields_rect_per_line(
        self, wrap_pdf_bytes: bytes
    ) -> None:
        rects = locate_words(wrap_pdf_bytes, 1, "beta gamma")
        assert len(rects) == 2
        assert rects[0][1] < rects[1][1]  # first rect sits above the second

    def test_blank_or_empty_snippet_returns_empty(self, pdf_bytes: bytes) -> None:
        assert locate_words(pdf_bytes, 2, "") == []
        assert locate_words(pdf_bytes, 2, "   ") == []
        assert locate_words(pdf_bytes, 2, "!!!") == []

    def test_page_number_out_of_range_returns_empty(self, pdf_bytes: bytes) -> None:
        assert locate_words(pdf_bytes, 0, _SENTENCE) == []
        assert locate_words(pdf_bytes, 99, _SENTENCE) == []