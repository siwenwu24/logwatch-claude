"""Rendering of aggregated statistics into human- and machine-readable form."""

from __future__ import annotations

import json

from .aggregator import Summary

__all__ = ["format_text", "format_json"]

_WIDTH = 52


def _pct(part: int, whole: int) -> str:
    return f"{(100.0 * part / whole):5.1f}%" if whole else "  0.0%"


def _bar(part: int, whole: int, width: int = 20) -> str:
    if whole <= 0 or part <= 0:
        return ""
    # Always show at least one block so small-but-present levels stay visible.
    return "#" * max(1, int(round(width * part / whole)))


def _section(title: str) -> str:
    """A ``-- title ----`` rule padded out to the report width."""
    prefix = f"-- {title} "
    return prefix + "-" * max(3, _WIDTH - len(prefix))


def format_text(summary: Summary, top_n: int = 10) -> str:
    """Render a summary as an aligned plain-text report."""
    lines = []
    lines.append("=" * _WIDTH)
    lines.append("logwatch report")
    lines.append("=" * _WIDTH)

    lines.append(f"Files processed   : {summary.files_processed}")
    lines.append(f"Lines processed   : {summary.total_lines}")
    lines.append(f"  parsed          : {summary.parsed_lines}")
    lines.append(f"  malformed       : {summary.malformed_lines}")
    if summary.blank_lines:
        lines.append(f"  blank (skipped) : {summary.blank_lines}")
    if summary.first_timestamp and summary.last_timestamp:
        lines.append(f"Time range        : {summary.first_timestamp.isoformat()}")
        lines.append(f"                 -> {summary.last_timestamp.isoformat()}")

    lines.append("")
    lines.append(_section("Lines by level"))
    if not summary.level_counts:
        lines.append("(no log lines parsed)")
    else:
        width = max(len(level) for level in summary.level_counts)
        for level, count in summary.level_counts.items():
            pct = _pct(count, summary.parsed_lines)
            bar = _bar(count, summary.parsed_lines)
            lines.append(f"{level:<{width}}  {count:>7}  {pct}  {bar}")

    lines.append("")
    lines.append(_section(f"Top {top_n} keywords"))
    keywords = summary.top_keywords
    if not keywords:
        lines.append("(no keywords found)")
    else:
        width = max(len(word) for word, _ in keywords)
        for rank, (word, count) in enumerate(keywords, start=1):
            lines.append(f"{rank:>2}. {word:<{width}}  {count:>7}")
        lines.append("")
        lines.append(f"({summary.distinct_keywords} distinct keywords overall)")

    lines.append("=" * _WIDTH)
    return "\n".join(lines)


def format_json(summary: Summary, indent: int = 2) -> str:
    """Render a summary as JSON."""
    return json.dumps(summary.to_dict(), indent=indent, sort_keys=False)
