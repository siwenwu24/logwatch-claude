"""Tests for single-line parsing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from logwatch.parser import ParsedLine, canonical_level, parse_line


class TestAcceptedFormats:
    @pytest.mark.parametrize(
        "line, expected_ts",
        [
            (
                "2026-08-23T10:00:00 ERROR boom",
                datetime(2026, 8, 23, 10, 0, 0),
            ),
            (
                "2026-08-23 10:00:00 ERROR boom",
                datetime(2026, 8, 23, 10, 0, 0),
            ),
            (
                "2026-08-23T10:00:00.123 ERROR boom",
                datetime(2026, 8, 23, 10, 0, 0, 123000),
            ),
            (
                "2026-08-23T10:00:00,123 ERROR boom",
                datetime(2026, 8, 23, 10, 0, 0, 123000),
            ),
            (
                "2026-08-23T10:00:00Z ERROR boom",
                datetime(2026, 8, 23, 10, 0, 0, tzinfo=timezone.utc),
            ),
            (
                "2026-08-23T10:00:00+02:00 ERROR boom",
                datetime(2026, 8, 23, 10, 0, 0, tzinfo=timezone(timedelta(hours=2))),
            ),
            ("2026-08-23 ERROR boom", datetime(2026, 8, 23)),
        ],
    )
    def test_timestamp_variants(self, line, expected_ts):
        parsed = parse_line(line)
        assert parsed is not None
        assert parsed.timestamp == expected_ts
        assert parsed.level == "ERROR"
        assert parsed.message == "boom"

    @pytest.mark.parametrize(
        "line",
        [
            "2026-08-23T10:00:00 ERROR boom",
            "[2026-08-23T10:00:00] ERROR boom",
            "2026-08-23T10:00:00 [ERROR] boom",
            "[2026-08-23T10:00:00] [ERROR] boom",
            "2026-08-23T10:00:00 ERROR: boom",
            "2026-08-23T10:00:00 ERROR - boom",
            "   2026-08-23T10:00:00 ERROR boom   ",
            "2026-08-23T10:00:00\tERROR\tboom",
        ],
    )
    def test_field_decorations(self, line):
        parsed = parse_line(line)
        assert parsed is not None
        assert parsed.level == "ERROR"
        assert parsed.message == "boom"

    @pytest.mark.parametrize(
        "fraction, expected_microsecond",
        [
            (".1", 100000),
            (".12", 120000),
            (".123", 123000),
            (".1234", 123400),
            (".123456", 123456),
            (".123456789", 123456),  # truncated, not rounded
        ],
    )
    def test_any_number_of_fractional_digits(self, fraction, expected_microsecond):
        # Python 3.9/3.10 only accept 3 or 6 digits natively.
        parsed = parse_line(f"2026-08-23T10:00:00{fraction} INFO tick")
        assert parsed is not None
        assert parsed.timestamp.microsecond == expected_microsecond

    @pytest.mark.parametrize("offset", ["+02:00", "+0200"])
    def test_offset_with_or_without_a_colon(self, offset):
        parsed = parse_line(f"2026-08-23T10:00:00{offset} INFO tick")
        assert parsed is not None
        assert parsed.timestamp.utcoffset() == timedelta(hours=2)

    def test_message_preserves_internal_content(self):
        line = "2026-08-23T10:00:00 INFO GET /v1/users?id=3 -> 200 in 12ms"
        parsed = parse_line(line)
        assert parsed.message == "GET /v1/users?id=3 -> 200 in 12ms"

    def test_raw_is_retained_without_newline(self):
        parsed = parse_line("2026-08-23T10:00:00 INFO hello\n")
        assert parsed.raw == "2026-08-23T10:00:00 INFO hello"

    def test_empty_message_is_allowed(self):
        parsed = parse_line("2026-08-23T10:00:00 INFO")
        assert parsed is not None
        assert parsed.message == ""

    def test_result_is_hashable_and_frozen(self):
        parsed = parse_line("2026-08-23T10:00:00 INFO hello")
        assert isinstance(parsed, ParsedLine)
        hash(parsed)
        with pytest.raises(Exception):
            parsed.level = "ERROR"


class TestLevels:
    @pytest.mark.parametrize(
        "written, expected",
        [
            ("INFO", "INFO"),
            ("info", "INFO"),
            ("Info", "INFO"),
            ("WARN", "WARNING"),
            ("warn", "WARNING"),
            ("WARNING", "WARNING"),
            ("ERR", "ERROR"),
            ("FATAL", "CRITICAL"),
            ("CRIT", "CRITICAL"),
            ("PANIC", "CRITICAL"),
            ("VERBOSE", "TRACE"),
        ],
    )
    def test_aliases_normalise(self, written, expected):
        parsed = parse_line(f"2026-08-23T10:00:00 {written} something happened")
        assert parsed is not None
        assert parsed.level == expected

    def test_canonical_level_helper(self):
        assert canonical_level("warn") == "WARNING"
        assert canonical_level("AUDIT") == "AUDIT"

    def test_custom_uppercase_level_is_accepted(self):
        parsed = parse_line("2026-08-23T10:00:00 AUDIT permission granted")
        assert parsed is not None
        assert parsed.level == "AUDIT"

    def test_lowercase_prose_is_not_treated_as_a_level(self):
        # Without this rule any sentence starting after a date becomes a level.
        assert parse_line("2026-08-23 the server restarted itself") is None


class TestMalformed:
    @pytest.mark.parametrize(
        "line",
        [
            "",
            "   ",
            "\n",
            "\t\n",
        ],
    )
    def test_blank_lines(self, line):
        assert parse_line(line) is None

    @pytest.mark.parametrize(
        "line",
        [
            "no timestamp at all ERROR boom",
            "Traceback (most recent call last):",
            '  File "/app/worker/jobs.py", line 88, in run',
            "psycopg.OperationalError: connection pool exhausted",
            "08/23/2026 10:00:00 ERROR wrong date format",
            "2026-08-23T10:00:00ERROR missing separator",
            "ERROR 2026-08-23T10:00:00 fields swapped",
            "26-08-23 10:00:00 INFO two digit year",
        ],
    )
    def test_unparseable_lines_return_none(self, line):
        assert parse_line(line) is None

    @pytest.mark.parametrize(
        "line",
        [
            "2026-13-01T10:00:00 INFO month thirteen",
            "2026-08-45T10:00:00 INFO day forty five",
            "2026-02-30 INFO february thirtieth",
            "2026-08-23T25:00:00 INFO hour twenty five",
            "2026-08-23T10:61:00 INFO minute sixty one",
        ],
    )
    def test_impossible_dates_are_rejected(self, line):
        assert parse_line(line) is None

    def test_overlong_level_token_is_rejected(self):
        assert parse_line("2026-08-23T10:00:00 SUPERCALIFRAGILISTIC nope") is None
