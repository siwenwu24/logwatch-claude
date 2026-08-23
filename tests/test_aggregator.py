"""Tests for statistic accumulation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from logwatch.aggregator import LogAggregator


class TestCounting:
    def test_counts_levels(self, populated):
        assert populated.level_counts == {
            "INFO": 1,
            "DEBUG": 1,
            "WARNING": 1,
            "ERROR": 2,
            "CRITICAL": 1,
        }

    def test_totals(self, populated):
        assert populated.total_lines == 6
        assert populated.parsed_lines == 6
        assert populated.malformed_lines == 0

    def test_add_line_returns_the_parsed_line(self, aggregator):
        parsed = aggregator.add_line("2026-08-23T10:00:00 INFO hello world")
        assert parsed.level == "INFO"
        assert parsed.message == "hello world"

    def test_malformed_lines_are_counted_but_not_parsed(self, aggregator):
        assert aggregator.add_line("garbage without a timestamp") is None
        assert aggregator.total_lines == 1
        assert aggregator.parsed_lines == 0
        assert aggregator.malformed_lines == 1
        assert aggregator.level_counts == {}

    def test_blank_lines_are_excluded_from_the_total(self, aggregator):
        aggregator.add_lines(["", "   ", "\n"])
        assert aggregator.total_lines == 0
        assert aggregator.blank_lines == 3

    def test_add_lines_returns_parsed_count(self, aggregator):
        parsed = aggregator.add_lines(
            [
                "2026-08-23T10:00:00 INFO one",
                "not a log line",
                "2026-08-23T10:00:01 INFO two",
                "",
            ]
        )
        assert parsed == 2
        assert aggregator.total_lines == 3
        assert aggregator.malformed_lines == 1
        assert aggregator.blank_lines == 1

    def test_add_text_splits_on_newlines(self, aggregator):
        aggregator.add_text(
            "2026-08-23T10:00:00 INFO one\n2026-08-23T10:00:01 ERROR two\n"
        )
        assert aggregator.parsed_lines == 2

    def test_level_aliases_are_folded_together(self, aggregator):
        aggregator.add_lines(
            [
                "2026-08-23T10:00:00 WARN first",
                "2026-08-23T10:00:01 WARNING second",
                "2026-08-23T10:00:02 warn third",
            ]
        )
        assert aggregator.level_counts == {"WARNING": 3}


class TestKeywords:
    def test_keywords_are_counted_across_lines(self, populated):
        assert populated.keyword_counts["database"] == 3
        assert populated.keyword_counts["connection"] == 3
        assert populated.keyword_counts["failed"] == 2

    def test_top_keywords_is_ordered_by_frequency(self, populated):
        top = populated.top_keywords(3)
        counts = [count for _, count in top]
        assert counts == sorted(counts, reverse=True)
        # "connection" and "database" tie at 3; alphabetical order decides.
        assert top[:2] == [("connection", 3), ("database", 3)]

    def test_top_keywords_breaks_ties_alphabetically(self, aggregator):
        aggregator.add_line("2026-08-23T10:00:00 INFO zebra apple mango")
        assert aggregator.top_keywords(3) == [("apple", 1), ("mango", 1), ("zebra", 1)]

    def test_top_keywords_respects_the_limit(self, populated):
        assert len(populated.top_keywords(2)) == 2

    def test_top_keywords_limit_larger_than_available(self, populated):
        assert len(populated.top_keywords(1000)) == len(populated.keyword_counts)

    @pytest.mark.parametrize("limit", [0, -1, -10])
    def test_non_positive_limit_returns_nothing(self, populated, limit):
        assert populated.top_keywords(limit) == []

    def test_min_keyword_length_is_honoured(self):
        aggregator = LogAggregator(min_keyword_length=8)
        aggregator.add_line("2026-08-23T10:00:00 ERROR database connection failed")
        assert set(aggregator.keyword_counts) == {"database", "connection"}

    def test_custom_stopwords_are_honoured(self):
        aggregator = LogAggregator(stopwords=frozenset({"database"}))
        aggregator.add_line("2026-08-23T10:00:00 ERROR database failure")
        assert set(aggregator.keyword_counts) == {"failure"}

    def test_malformed_lines_contribute_no_keywords(self, aggregator):
        aggregator.add_line("this unparseable line mentions database repeatedly")
        assert aggregator.keyword_counts == {}


class TestTimestamps:
    def test_range_tracks_earliest_and_latest(self, aggregator):
        aggregator.add_lines(
            [
                "2026-08-23T10:00:05 INFO middle",
                "2026-08-23T09:00:00 INFO earliest",
                "2026-08-23T11:00:00 INFO latest",
            ]
        )
        assert aggregator.first_timestamp == datetime(2026, 8, 23, 9, 0, 0)
        assert aggregator.last_timestamp == datetime(2026, 8, 23, 11, 0, 0)

    def test_range_is_none_when_nothing_parsed(self, aggregator):
        aggregator.add_line("nonsense")
        assert aggregator.first_timestamp is None
        assert aggregator.last_timestamp is None

    def test_mixing_naive_and_aware_timestamps_does_not_raise(self, aggregator):
        # Comparing naive and aware datetimes is a TypeError in Python; a
        # directory with mixed formats must not crash the aggregator.
        aggregator.add_line("2026-08-23T10:00:00 INFO naive")
        aggregator.add_line("2026-08-23T10:00:00Z INFO aware")
        assert aggregator.parsed_lines == 2
        assert aggregator.first_timestamp is not None


class TestFiles:
    def test_add_file_reads_and_registers(self, tmp_path, aggregator):
        path = tmp_path / "x.log"
        path.write_text(
            "2026-08-23T10:00:00 INFO one\n2026-08-23T10:00:01 ERROR two\n"
        )
        assert aggregator.add_file(path) == 2
        assert aggregator.summary().files_processed == 1

    def test_add_file_survives_undecodable_bytes(self, tmp_path, aggregator):
        path = tmp_path / "bin.log"
        path.write_bytes(b"2026-08-23T10:00:00 INFO caf\xe9 latte\n")
        assert aggregator.add_file(path) == 1

    def test_the_same_file_is_only_counted_once(self, tmp_path, aggregator):
        path = tmp_path / "x.log"
        path.write_text("2026-08-23T10:00:00 INFO one\n")
        aggregator.add_file(path)
        aggregator.add_file(path)
        assert aggregator.summary().files_processed == 1
        assert aggregator.parsed_lines == 2

    def test_missing_file_raises(self, tmp_path, aggregator):
        with pytest.raises(OSError):
            aggregator.add_file(tmp_path / "nope.log")


class TestSummary:
    def test_summary_fields(self, populated):
        summary = populated.summary(top_n=2)
        assert summary.total_lines == 6
        assert summary.parsed_lines == 6
        assert summary.files_processed == 0
        assert len(summary.top_keywords) == 2
        assert summary.distinct_keywords == len(populated.keyword_counts)

    def test_summary_levels_are_severity_ordered(self, populated):
        assert list(populated.summary().level_counts) == [
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
            "CRITICAL",
        ]

    def test_custom_levels_sort_after_canonical_ones(self, aggregator):
        aggregator.add_lines(
            [
                "2026-08-23T10:00:00 AUDIT custom level",
                "2026-08-23T10:00:01 INFO canonical level",
                "2026-08-23T10:00:02 ZEBRA another custom level",
            ]
        )
        assert list(aggregator.summary().level_counts) == ["INFO", "AUDIT", "ZEBRA"]

    def test_summary_is_a_snapshot_not_a_live_view(self, aggregator):
        aggregator.add_line("2026-08-23T10:00:00 INFO one")
        summary = aggregator.summary()
        aggregator.add_line("2026-08-23T10:00:01 INFO two")
        assert summary.total_lines == 1

    def test_to_dict_is_json_ready(self, populated):
        import json

        data = populated.summary(top_n=3).to_dict()
        json.dumps(data)  # must not raise
        assert data["level_counts"]["ERROR"] == 2
        assert data["top_keywords"][0] == {"keyword": "connection", "count": 3}
        assert data["first_timestamp"] == "2026-08-23T10:00:00"

    def test_to_dict_with_no_timestamps(self, aggregator):
        data = aggregator.summary().to_dict()
        assert data["first_timestamp"] is None
        assert data["last_timestamp"] is None

    def test_empty_aggregator_summary(self, aggregator):
        summary = aggregator.summary()
        assert summary.total_lines == 0
        assert summary.level_counts == {}
        assert summary.top_keywords == []


class TestMerge:
    def test_merge_combines_counts(self):
        a, b = LogAggregator(), LogAggregator()
        a.add_line("2026-08-23T10:00:00 ERROR database down")
        b.add_line("2026-08-23T11:00:00 ERROR database down")
        b.add_line("bad line")
        a.merge(b)
        assert a.parsed_lines == 2
        assert a.malformed_lines == 1
        assert a.level_counts == {"ERROR": 2}
        assert a.keyword_counts["database"] == 2

    def test_merge_widens_the_time_range(self):
        a, b = LogAggregator(), LogAggregator()
        a.add_line("2026-08-23T10:00:00 INFO a")
        b.add_line("2026-08-23T08:00:00 INFO b")
        a.merge(b)
        assert a.first_timestamp == datetime(2026, 8, 23, 8, 0, 0)
        assert a.last_timestamp == datetime(2026, 8, 23, 10, 0, 0)

    def test_merge_unions_files(self, tmp_path):
        a, b = LogAggregator(), LogAggregator()
        a.register_file(tmp_path / "one.log")
        b.register_file(tmp_path / "two.log")
        b.register_file(tmp_path / "one.log")
        a.merge(b)
        assert a.summary().files_processed == 2

    def test_merge_returns_self_for_chaining(self):
        a = LogAggregator()
        assert a.merge(LogAggregator()) is a

    def test_merging_an_empty_aggregator_changes_nothing(self, populated):
        before = populated.summary()
        populated.merge(LogAggregator())
        assert populated.summary().to_dict() == before.to_dict()
