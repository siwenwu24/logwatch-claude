"""Accumulates statistics across many log lines."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .keywords import DEFAULT_MIN_LENGTH, STOPWORDS, tokenize
from .parser import LEVEL_ORDER, ParsedLine, parse_line

__all__ = ["LogAggregator", "Summary"]


def _level_sort_key(level: str) -> Tuple[int, str]:
    """Canonical levels sort by severity; custom levels sort after, by name."""
    try:
        return (LEVEL_ORDER.index(level), "")
    except ValueError:
        return (len(LEVEL_ORDER), level)


@dataclass
class Summary:
    """An immutable view of the aggregator's state, ready to be rendered."""

    total_lines: int
    parsed_lines: int
    malformed_lines: int
    blank_lines: int
    files_processed: int
    level_counts: Dict[str, int]
    top_keywords: List[Tuple[str, int]]
    distinct_keywords: int
    first_timestamp: Optional[datetime] = None
    last_timestamp: Optional[datetime] = None

    def to_dict(self) -> dict:
        """JSON-serialisable form (datetimes become ISO strings)."""
        return {
            "total_lines": self.total_lines,
            "parsed_lines": self.parsed_lines,
            "malformed_lines": self.malformed_lines,
            "blank_lines": self.blank_lines,
            "files_processed": self.files_processed,
            "level_counts": self.level_counts,
            "top_keywords": [
                {"keyword": word, "count": count} for word, count in self.top_keywords
            ],
            "distinct_keywords": self.distinct_keywords,
            "first_timestamp": (
                self.first_timestamp.isoformat() if self.first_timestamp else None
            ),
            "last_timestamp": (
                self.last_timestamp.isoformat() if self.last_timestamp else None
            ),
        }


@dataclass
class LogAggregator:
    """Counts log lines by level and tallies the keywords in their messages.

    The aggregator is incremental: feed it lines as they arrive and ask for a
    :meth:`summary` whenever you want a snapshot.
    """

    min_keyword_length: int = DEFAULT_MIN_LENGTH
    stopwords: frozenset = STOPWORDS

    total_lines: int = 0
    parsed_lines: int = 0
    malformed_lines: int = 0
    blank_lines: int = 0
    level_counts: Counter = field(default_factory=Counter)
    keyword_counts: Counter = field(default_factory=Counter)
    files_seen: set = field(default_factory=set)
    first_timestamp: Optional[datetime] = None
    last_timestamp: Optional[datetime] = None

    # -- ingestion ---------------------------------------------------------

    def add_line(self, line: str) -> Optional[ParsedLine]:
        """Ingest a single raw line. Returns the parsed line, or ``None``."""
        if not line.strip():
            self.blank_lines += 1
            return None

        self.total_lines += 1
        parsed = parse_line(line)
        if parsed is None:
            self.malformed_lines += 1
            return None

        self.parsed_lines += 1
        self.level_counts[parsed.level] += 1
        self.keyword_counts.update(
            tokenize(
                parsed.message,
                min_length=self.min_keyword_length,
                stopwords=self.stopwords,
            )
        )
        self._track_timestamp(parsed.timestamp)
        return parsed

    def add_lines(self, lines: Iterable[str]) -> int:
        """Ingest many lines; returns how many parsed successfully."""
        parsed = 0
        for line in lines:
            if self.add_line(line) is not None:
                parsed += 1
        return parsed

    def add_text(self, text: str) -> int:
        """Ingest a block of text, splitting it into lines."""
        return self.add_lines(text.splitlines())

    def add_file(self, path: Path, encoding: str = "utf-8") -> int:
        """Ingest an entire file. Undecodable bytes are replaced, not fatal."""
        path = Path(path)
        with path.open("r", encoding=encoding, errors="replace") as handle:
            count = self.add_lines(handle)
        self.files_seen.add(str(path))
        return count

    def register_file(self, path) -> None:
        """Record that a file was processed, without reading it here."""
        self.files_seen.add(str(path))

    def _track_timestamp(self, timestamp: Optional[datetime]) -> None:
        if timestamp is None:
            return
        # Mixing naive and aware datetimes raises on comparison; keep whichever
        # kind we saw first rather than crashing on a mixed-format directory.
        for attr, better in (("first_timestamp", True), ("last_timestamp", False)):
            current = getattr(self, attr)
            if current is None:
                setattr(self, attr, timestamp)
                continue
            if (current.tzinfo is None) != (timestamp.tzinfo is None):
                continue
            if (timestamp < current) if better else (timestamp > current):
                setattr(self, attr, timestamp)

    # -- reporting ---------------------------------------------------------

    def top_keywords(self, limit: int = 10) -> List[Tuple[str, int]]:
        """Most frequent keywords, ties broken alphabetically for stable output."""
        if limit <= 0:
            return []
        ranked = sorted(self.keyword_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        return ranked[:limit]

    def sorted_levels(self) -> List[Tuple[str, int]]:
        """Level counts ordered by severity."""
        return sorted(self.level_counts.items(), key=lambda kv: _level_sort_key(kv[0]))

    def summary(self, top_n: int = 10) -> Summary:
        return Summary(
            total_lines=self.total_lines,
            parsed_lines=self.parsed_lines,
            malformed_lines=self.malformed_lines,
            blank_lines=self.blank_lines,
            files_processed=len(self.files_seen),
            level_counts=dict(self.sorted_levels()),
            top_keywords=self.top_keywords(top_n),
            distinct_keywords=len(self.keyword_counts),
            first_timestamp=self.first_timestamp,
            last_timestamp=self.last_timestamp,
        )

    def merge(self, other: "LogAggregator") -> "LogAggregator":
        """Fold another aggregator's counts into this one."""
        self.total_lines += other.total_lines
        self.parsed_lines += other.parsed_lines
        self.malformed_lines += other.malformed_lines
        self.blank_lines += other.blank_lines
        self.level_counts.update(other.level_counts)
        self.keyword_counts.update(other.keyword_counts)
        self.files_seen |= other.files_seen
        self._track_timestamp(other.first_timestamp)
        self._track_timestamp(other.last_timestamp)
        return self
