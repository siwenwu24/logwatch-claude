"""Shared fixtures."""

from __future__ import annotations

import pytest

from logwatch.aggregator import LogAggregator

SAMPLE_LINES = [
    "2026-08-23T10:00:00 INFO service started listening on port 8080",
    "2026-08-23T10:00:05 DEBUG connection pool warmed",
    "2026-08-23T10:00:09 WARNING slow query detected on orders table",
    "2026-08-23T10:00:12 ERROR database connection failed",
    "2026-08-23T10:00:13 ERROR database connection failed again",
    "2026-08-23T10:00:20 CRITICAL primary database unreachable",
]


@pytest.fixture
def aggregator() -> LogAggregator:
    return LogAggregator()


@pytest.fixture
def populated(aggregator: LogAggregator) -> LogAggregator:
    aggregator.add_lines(SAMPLE_LINES)
    return aggregator


@pytest.fixture
def log_dir(tmp_path):
    """A directory with two small log files and one non-log file."""
    directory = tmp_path / "logs"
    directory.mkdir()
    (directory / "a.log").write_text(
        "2026-08-23T10:00:00 INFO alpha started\n"
        "2026-08-23T10:00:01 ERROR alpha crashed\n"
    )
    (directory / "b.log").write_text(
        "2026-08-23T10:00:02 INFO beta started\n"
        "2026-08-23T10:00:03 WARNING beta degraded\n"
    )
    (directory / "notes.txt").write_text("2026-08-23T10:00:04 INFO ignore me\n")
    return directory
