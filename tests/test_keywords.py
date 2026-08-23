"""Tests for keyword extraction."""

from __future__ import annotations

import pytest

from logwatch.keywords import STOPWORDS, tokenize


def toks(text, **kwargs):
    return list(tokenize(text, **kwargs))


class TestTokenize:
    def test_basic_lowercasing(self):
        assert toks("Database Connection FAILED") == [
            "database",
            "connection",
            "failed",
        ]

    def test_punctuation_is_stripped(self):
        assert toks("timeout, retrying... (attempt)") == [
            "timeout",
            "retrying",
            "attempt",
        ]

    def test_stopwords_are_removed(self):
        assert toks("the database is not the problem") == ["database", "problem"]

    def test_short_tokens_are_removed(self):
        assert toks("db is up ok now") == []

    def test_min_length_is_configurable(self):
        assert toks("db up", min_length=2) == ["db"]

    def test_custom_stopwords(self):
        assert toks("alpha beta gamma", stopwords={"beta"}) == ["alpha", "gamma"]

    def test_custom_stopwords_accepts_any_iterable(self):
        assert toks("alpha beta", stopwords=["beta"]) == ["alpha"]

    def test_pure_numbers_are_dropped(self):
        assert toks("completed in 3400 ms at 10:00:00") == ["completed"]

    def test_alphanumeric_identifiers_are_kept(self):
        assert toks("worker w3 job 10021 pod api7x") == [
            "worker",
            "job",
            "pod",
            "api7x",
        ]

    def test_long_hex_blobs_are_dropped(self):
        assert toks("commit deadbeefcafe1234 rebuilt bundle") == [
            "commit",
            "rebuilt",
            "bundle",
        ]

    def test_short_hex_like_words_are_kept(self):
        # "added" is real English that happens to be hex characters.
        assert "added" in toks("added record")

    def test_underscores_are_kept_inside_but_trimmed_outside(self):
        assert toks("__users_email_idx__ scanned") == ["users_email_idx", "scanned"]

    def test_empty_text(self):
        assert toks("") == []

    def test_duplicates_are_preserved_for_counting(self):
        assert toks("retry retry retry") == ["retry", "retry", "retry"]

    def test_returns_an_iterator_not_a_list(self):
        result = tokenize("lazy evaluation please")
        assert iter(result) is result

    @pytest.mark.parametrize("word", ["the", "and", "with", "from", "that"])
    def test_common_function_words_are_stopwords(self, word):
        assert word in STOPWORDS

    @pytest.mark.parametrize(
        "word", ["failed", "timeout", "error", "retry", "connection", "database"]
    )
    def test_signal_words_are_not_stopwords(self, word):
        assert word not in STOPWORDS
