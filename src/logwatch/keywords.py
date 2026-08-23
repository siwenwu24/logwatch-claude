"""Keyword extraction from log message text."""

from __future__ import annotations

import re
from typing import Iterable, Iterator

__all__ = ["tokenize", "STOPWORDS", "DEFAULT_MIN_LENGTH"]

DEFAULT_MIN_LENGTH = 3

#: Function words plus a few log-specific fillers. Deliberately conservative:
#: words that carry signal in logs (failed, timeout, retry, ...) are kept.
STOPWORDS = frozenset(
    """
    a about after again against all also am an and any are as at be because
    been before being below between both but by can could did do does doing
    done down during each few for from further had has have having he her here
    him his how i if in into is it its just me more most my no nor not now of
    off on once only or other our out over own same she should so some still
    such than that the their them then there these they this those through to
    too under until up upon very was we were what when where which while who
    whom why will with would you your
    """.split()
)

# Words are ASCII-letter-initial runs; this drops pure numbers such as
# timestamps, ports and byte counts without needing a separate rule.
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")

_HEX_RE = re.compile(r"^[0-9a-f]+$")


def _is_noise(token: str) -> bool:
    """Filter out opaque identifiers: long hex blobs, uuid chunks, hashes."""
    return len(token) >= 8 and _HEX_RE.match(token) is not None


def tokenize(
    text: str,
    min_length: int = DEFAULT_MIN_LENGTH,
    stopwords: Iterable[str] = STOPWORDS,
) -> Iterator[str]:
    """Yield normalised keywords from a message.

    Tokens are lower-cased, stripped of surrounding punctuation, and filtered
    to drop stopwords, very short tokens and opaque hex identifiers.
    """
    stops = stopwords if isinstance(stopwords, frozenset) else frozenset(stopwords)
    for match in _TOKEN_RE.finditer(text):
        token = match.group(0).lower().strip("_")
        if len(token) < min_length:
            continue
        if token in stops:
            continue
        if _is_noise(token):
            continue
        yield token
