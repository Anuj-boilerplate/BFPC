"""Unit tests for the sentence ranker (pure stdlib, no model)."""

from __future__ import annotations

from bfpc.index.sentence_ranker import rank_sentences


class TestRankSentences:
    def test_returns_most_relevant_sentence_first(self) -> None:
        chunk = "Foo bar. Bar baz qux. Qux foo."
        assert rank_sentences("bar baz", chunk, top_n=1) == ["Bar baz qux."]

    def test_returns_top_n_in_score_order(self) -> None:
        chunk = "Alpha beta gamma. Alpha beta. Delta."
        ranked = rank_sentences("alpha beta", chunk, top_n=2)
        assert ranked == ["Alpha beta.", "Alpha beta gamma."]

    def test_skips_zero_score_sentences_with_full_text_fallback(self) -> None:
        chunk = "Completely unrelated. Cactus mongoose."
        assert rank_sentences("trout fishing", chunk, top_n=1) == [chunk]

    def test_empty_text_returns_empty(self) -> None:
        assert rank_sentences("query", "") == []
        assert rank_sentences("query", "   \n\t ") == []

    def test_single_sentence_without_punctuation(self) -> None:
        assert rank_sentences("hello", "hello world here") == ["hello world here"]

    def test_blank_query_falls_back_to_full_text(self) -> None:
        chunk = "Some content here. More content."
        assert rank_sentences("   ", chunk) == [chunk]

    def test_top_n_bigger_than_sentence_count_returns_all(self) -> None:
        chunk = "One. Two. Three."
        result = rank_sentences("one", chunk, top_n=10)
        assert len(result) == 3
        assert result[0] == "One."

    def test_non_positive_top_n_returns_empty(self) -> None:
        assert rank_sentences("q", "One. Two.", top_n=0) == []
        assert rank_sentences("q", "One. Two.", top_n=-1) == []

    def test_ties_keep_original_order(self) -> None:
        chunk = "First alpha. Second alpha."
        assert rank_sentences("alpha", chunk, top_n=2) == ["First alpha.", "Second alpha."]