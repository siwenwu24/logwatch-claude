"""Command line interface for logwatch."""

from __future__ import annotations

import signal
import sys
from pathlib import Path

import click

from . import __version__
from .aggregator import LogAggregator
from .report import format_json, format_text
from .watcher import DirectoryWatcher

DEFAULT_DIR = "./logs"

_dir_option = click.option(
    "--dir",
    "-d",
    "directory",
    default=DEFAULT_DIR,
    show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory to read .log files from.",
)
_top_option = click.option(
    "--top",
    "-n",
    default=10,
    show_default=True,
    type=click.IntRange(min=0),
    help="How many keywords to show.",
)
_json_option = click.option(
    "--json", "as_json", is_flag=True, help="Emit JSON instead of a text report."
)
_pattern_option = click.option(
    "--pattern",
    default="*.log",
    show_default=True,
    help="Glob used to select log files.",
)
_recursive_option = click.option(
    "--recursive", is_flag=True, help="Also search sub-directories."
)
_min_length_option = click.option(
    "--min-keyword-length",
    default=3,
    show_default=True,
    type=click.IntRange(min=1),
    help="Ignore keywords shorter than this.",
)


def _build(directory, pattern, recursive, min_keyword_length):
    aggregator = LogAggregator(min_keyword_length=min_keyword_length)
    watcher = DirectoryWatcher(
        directory=directory,
        aggregator=aggregator,
        pattern=pattern,
        recursive=recursive,
    )
    return aggregator, watcher


def _emit(aggregator, top, as_json) -> None:
    summary = aggregator.summary(top_n=top)
    click.echo(format_json(summary) if as_json else format_text(summary, top_n=top))


def _require_directory(directory: Path) -> None:
    """click's ``Path(file_okay=False)`` rejects files; we only add existence."""
    if not directory.exists():
        raise click.ClickException(f"directory does not exist: {directory}")


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="logwatch")
def main() -> None:
    """Aggregate and summarise structured log files."""


@main.command()
@_dir_option
@_top_option
@_json_option
@_pattern_option
@_recursive_option
@_min_length_option
def report(directory, top, as_json, pattern, recursive, min_keyword_length) -> None:
    """Scan a directory once and print a summary."""
    _require_directory(directory)
    aggregator, watcher = _build(directory, pattern, recursive, min_keyword_length)

    if not watcher.discover():
        click.echo(f"No files matching {pattern!r} in {directory}", err=True)

    watcher.scan_once()
    _emit(aggregator, top, as_json)


@main.command()
@_dir_option
@_top_option
@_json_option
@_pattern_option
@_recursive_option
@_min_length_option
@click.option(
    "--interval",
    "-i",
    default=2.0,
    show_default=True,
    type=click.FloatRange(min=0.05),
    help="Seconds between polls.",
)
@click.option(
    "--iterations",
    default=None,
    type=click.IntRange(min=1),
    help="Stop after this many polls (default: run until interrupted).",
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Only print the final report, not one per poll.",
)
def watch(
    directory,
    top,
    as_json,
    pattern,
    recursive,
    min_keyword_length,
    interval,
    iterations,
    quiet,
) -> None:
    """Watch a directory and report as new log lines arrive."""
    _require_directory(directory)
    aggregator, watcher = _build(directory, pattern, recursive, min_keyword_length)

    click.echo(
        f"Watching {directory} for {pattern} (every {interval}s) - Ctrl-C to stop",
        err=True,
    )

    def on_poll(new_lines: int, _watcher) -> None:
        if quiet or new_lines == 0:
            return
        _emit(aggregator, top, as_json)

    # Make SIGTERM (docker stop) behave like Ctrl-C so the final report prints.
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt))

    try:
        watcher.run(interval=interval, on_poll=on_poll, max_iterations=iterations)
    except KeyboardInterrupt:
        click.echo("", err=True)

    watcher.flush_pending()
    click.echo("Final report:", err=True)
    _emit(aggregator, top, as_json)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
