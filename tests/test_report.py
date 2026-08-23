"""Tests for report rendering."""

from __future__ import annotations

import json

from logwatch.aggregator import LogAggregator
from logwatch.report import format_json, format_text


class TestTextReport:
    def test_contains_headline_figures(self, populated):
        text = format_text(populated.summary())
        assert "logwatch report" in text
        assert "Lines processed   : 6" in text

    def test_lists_every_level_with_its_count(self, populated):
        text = format_text(populated.summary())
        for level, count in populated.level_counts.items():
            assert level in text
        assert "ERROR" in text
        # ERROR has 2 of 6 lines.
        error_row = next(l for l in text.splitlines() if l.startswith("ERROR"))
        assert "2" in error_row and "33.3%" in error_row

    def test_lists_ranked_keywords(self, populated):
        text = format_text(populated.summary(top_n=3), top_n=3)
        assert "Top 3 keywords" in text
        assert " 1. connection" in text
        assert " 3. failed" in text

    def test_respects_the_keyword_limit(self, populated):
        text = format_text(populated.summary(top_n=2), top_n=2)
        assert " 2. " in text
        assert " 3. " not in text

    def test_shows_the_time_range(self, populated):
        text = format_text(populated.summary())
        assert "2026-08-23T10:00:00" in text
        assert "2026-08-23T10:00:20" in text

    def test_reports_malformed_lines(self, aggregator):
        aggregator.add_line("2026-08-23T10:00:00 INFO fine")
        aggregator.add_line("junk")
        text = format_text(aggregator.summary())
        assert "malformed       : 1" in text

    def test_blank_line_row_is_omitted_when_there_are_none(self, populated):
        assert "blank" not in format_text(populated.summary())

    def test_blank_line_row_appears_when_relevant(self, aggregator):
        aggregator.add_line("")
        assert "blank (skipped) : 1" in format_text(aggregator.summary())

    def test_empty_input_renders_without_crashing(self, aggregator):
        text = format_text(aggregator.summary())
        assert "(no log lines parsed)" in text
        assert "(no keywords found)" in text

    def test_levels_with_no_keywords_render(self, aggregator):
        # A parsed line whose message is entirely stopwords/short tokens.
        aggregator.add_line("2026-08-23T10:00:00 INFO it is up")
        text = format_text(aggregator.summary())
        assert "INFO" in text
        assert "(no keywords found)" in text

    def test_every_present_level_gets_a_visible_bar(self, aggregator):
        aggregator.add_lines(
            ["2026-08-23T10:00:00 INFO x"] * 200
            + ["2026-08-23T10:00:01 CRITICAL rare event"]
        )
        text = format_text(aggregator.summary())
        critical_row = next(
            l for l in text.splitlines() if l.startswith("CRITICAL")
        )
        assert "#" in critical_row

    def test_section_rules_are_padded_consistently(self, populated):
        text = format_text(populated.summary())
        rules = [l for l in text.splitlines() if l.startswith("--")]
        assert len(rules) == 2
        assert len({len(rule) for rule in rules}) == 1

    def test_output_has_no_trailing_newline(self, populated):
        assert not format_text(populated.summary()).endswith("\n")


class TestRendererEdgeCases:
    def test_levels_present_with_a_zero_parsed_total_do_not_divide_by_zero(self):
        from logwatch.aggregator import Summary

        summary = Summary(
            total_lines=0,
            parsed_lines=0,
            malformed_lines=0,
            blank_lines=0,
            files_processed=0,
            level_counts={"INFO": 0},
            top_keywords=[],
            distinct_keywords=0,
        )
        text = format_text(summary)
        assert "INFO" in text
        assert "0.0%" in text


class TestJsonReport:
    def test_is_valid_json(self, populated):
        data = json.loads(format_json(populated.summary()))
        assert data["total_lines"] == 6
        assert data["parsed_lines"] == 6

    def test_level_counts_round_trip(self, populated):
        data = json.loads(format_json(populated.summary()))
        assert data["level_counts"] == {
            "DEBUG": 1,
            "INFO": 1,
            "WARNING": 1,
            "ERROR": 2,
            "CRITICAL": 1,
        }

    def test_keywords_are_a_list_of_objects(self, populated):
        data = json.loads(format_json(populated.summary(top_n=2)))
        assert data["top_keywords"] == [
            {"keyword": "connection", "count": 3},
            {"keyword": "database", "count": 3},
        ]

    def test_empty_summary_is_still_valid_json(self):
        data = json.loads(format_json(LogAggregator().summary()))
        assert data["total_lines"] == 0
        assert data["top_keywords"] == []
        assert data["first_timestamp"] is None

    def test_indent_is_configurable(self, populated):
        compact = format_json(populated.summary(), indent=None)
        assert "\n" not in compact
