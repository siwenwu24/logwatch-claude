"""Parsing of individual log lines.

The expected shape of a line is ``TIMESTAMP LEVEL message``, for example::

    2026-08-23T10:00:00 ERROR database connection failed

Real log files are messier than that, so the parser tolerates a few common
variations (space instead of ``T``, bracketed fields, a ``:`` or ``-``
separator after the level, fractional seconds, timezone offsets) and reports
anything it cannot understand as malformed rather than raising.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

__all__ = [
    "ParsedLine",
    "parse_line",
    "canonical_level",
    "KNOWN_LEVELS",
    "LEVEL_ALIASES",
    "LEVEL_ORDER",
]

#: Levels we recognise regardless of the case they are written in.
KNOWN_LEVELS = frozenset(
    {"TRACE", "DEBUG", "INFO", "NOTICE", "WARNING", "ERROR", "CRITICAL"}
)

#: Common spellings that mean the same thing as a canonical level.
LEVEL_ALIASES = {
    "WARN": "WARNING",
    "WARNING": "WARNING",
    "ERR": "ERROR",
    "FATAL": "CRITICAL",
    "CRIT": "CRITICAL",
    "PANIC": "CRITICAL",
    "VERBOSE": "TRACE",
}

#: Severity ordering used when rendering reports. Levels outside this list are
#: sorted alphabetically after the ones that appear here.
LEVEL_ORDER = ("TRACE", "DEBUG", "INFO", "NOTICE", "WARNING", "ERROR", "CRITICAL")

_TIMESTAMP = r"""
    \d{4}-\d{2}-\d{2}                    # 2026-08-23
    (?:
        [T\ ]\d{2}:\d{2}:\d{2}           # T10:00:00 or ' 10:00:00'
        (?:[.,]\d{1,9})?                 # optional fractional seconds
        (?:Z|[+-]\d{2}:?\d{2})?          # optional timezone
    )?
"""

# Python 3.9/3.10 accept only 3 or 6 fractional digits and require a colon in
# the UTC offset. Normalising both keeps parsing identical across versions.
_FRACTION_RE = re.compile(r"\.(\d+)")
_COMPACT_OFFSET_RE = re.compile(r"([+-]\d{2})(\d{2})$")

_LINE_RE = re.compile(
    r"""^\s*
    \[?(?P<timestamp>""" + _TIMESTAMP + r""")\]?
    \s+
    \[?(?P<level>[A-Za-z]{2,12})(?![A-Za-z])\]?   # must be a whole word
    \s*[:\-]?\s*
    (?P<message>.*?)
    \s*$
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class ParsedLine:
    """A single successfully parsed log line."""

    timestamp: Optional[datetime]
    level: str
    message: str
    raw: str


def canonical_level(level: str) -> str:
    """Normalise a level spelling, e.g. ``warn`` and ``WARNING`` -> ``WARNING``."""
    upper = level.upper()
    return LEVEL_ALIASES.get(upper, upper)


def _parse_timestamp(value: str) -> Optional[datetime]:
    """Return a ``datetime`` for an ISO-ish timestamp, or ``None`` if invalid.

    ``None`` means the text looked like a date but is not a real one (e.g.
    ``2026-13-45``); the caller treats that as a malformed line.
    """
    normalised = value.replace(" ", "T").replace(",", ".")
    if normalised.endswith("Z"):
        normalised = normalised[:-1] + "+00:00"
    normalised = _FRACTION_RE.sub(
        lambda m: "." + m.group(1)[:6].ljust(6, "0"), normalised, count=1
    )
    normalised = _COMPACT_OFFSET_RE.sub(r"\1:\2", normalised)
    # A bare date is a valid timestamp for our purposes.
    try:
        return datetime.fromisoformat(normalised)
    except ValueError:
        return None


def parse_line(line: str) -> Optional[ParsedLine]:
    """Parse one log line.

    Returns ``None`` for blank lines and for anything that does not match the
    ``TIMESTAMP LEVEL message`` shape, including continuation lines such as
    stack traces.
    """
    if not line or not line.strip():
        return None

    match = _LINE_RE.match(line)
    if match is None:
        return None

    raw_level = match.group("level")
    level = canonical_level(raw_level)
    # An unknown word only counts as a level if it was written in upper case
    # (the usual convention for custom levels such as AUDIT or DEPLOY).
    # This keeps ordinary prose from being mistaken for a level.
    if level not in KNOWN_LEVELS and raw_level != raw_level.upper():
        return None

    timestamp = _parse_timestamp(match.group("timestamp"))
    if timestamp is None:
        return None

    return ParsedLine(
        timestamp=timestamp,
        level=level,
        message=match.group("message"),
        raw=line.rstrip("\n"),
    )
