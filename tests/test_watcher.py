"""Tests for incremental directory watching."""

from __future__ import annotations

from pathlib import Path

import pytest

from logwatch.aggregator import LogAggregator
from logwatch.watcher import DirectoryWatcher


def make_watcher(directory, **kwargs) -> DirectoryWatcher:
    return DirectoryWatcher(
        directory=directory, aggregator=LogAggregator(), **kwargs
    )


def append(path: Path, text: str) -> None:
    with path.open("a") as handle:
        handle.write(text)


class TestDiscovery:
    def test_finds_only_log_files(self, log_dir):
        names = [p.name for p in make_watcher(log_dir).discover()]
        assert names == ["a.log", "b.log"]

    def test_order_is_stable(self, log_dir):
        watcher = make_watcher(log_dir)
        assert watcher.discover() == watcher.discover()

    def test_missing_directory_yields_nothing(self, tmp_path):
        assert make_watcher(tmp_path / "absent").discover() == []

    def test_a_file_path_instead_of_a_directory_yields_nothing(self, log_dir):
        assert make_watcher(log_dir / "a.log").discover() == []

    def test_custom_pattern(self, log_dir):
        watcher = make_watcher(log_dir, pattern="*.txt")
        assert [p.name for p in watcher.discover()] == ["notes.txt"]

    def test_subdirectories_are_ignored_by_default(self, log_dir):
        nested = log_dir / "nested"
        nested.mkdir()
        (nested / "c.log").write_text("2026-08-23T10:00:00 INFO nested\n")
        assert [p.name for p in make_watcher(log_dir).discover()] == ["a.log", "b.log"]

    def test_recursive_finds_subdirectories(self, log_dir):
        nested = log_dir / "nested"
        nested.mkdir()
        (nested / "c.log").write_text("2026-08-23T10:00:00 INFO nested\n")
        watcher = make_watcher(log_dir, recursive=True)
        assert [p.name for p in watcher.discover()] == ["a.log", "b.log", "c.log"]

    def test_directory_is_coerced_to_a_path(self, log_dir):
        watcher = make_watcher(str(log_dir))
        assert isinstance(watcher.directory, Path)


class TestIncrementalReads:
    def test_first_poll_reads_everything(self, log_dir):
        watcher = make_watcher(log_dir)
        assert watcher.poll() == 4
        assert watcher.aggregator.parsed_lines == 4

    def test_second_poll_reads_nothing_new(self, log_dir):
        watcher = make_watcher(log_dir)
        watcher.poll()
        assert watcher.poll() == 0
        assert watcher.aggregator.parsed_lines == 4

    def test_appended_lines_are_picked_up(self, log_dir):
        watcher = make_watcher(log_dir)
        watcher.poll()
        append(log_dir / "a.log", "2026-08-23T10:05:00 ERROR alpha failed again\n")
        assert watcher.poll() == 1
        assert watcher.aggregator.level_counts["ERROR"] == 2

    def test_new_files_are_picked_up(self, log_dir):
        watcher = make_watcher(log_dir)
        watcher.poll()
        (log_dir / "c.log").write_text("2026-08-23T10:06:00 INFO gamma started\n")
        assert watcher.poll() == 1
        assert watcher.aggregator.summary().files_processed == 3

    def test_deleted_files_do_not_break_polling(self, log_dir):
        watcher = make_watcher(log_dir)
        watcher.poll()
        (log_dir / "a.log").unlink()
        assert watcher.poll() == 0

    def test_empty_file_is_handled(self, log_dir):
        (log_dir / "empty.log").write_text("")
        watcher = make_watcher(log_dir)
        assert watcher.poll() == 4

    def test_files_are_registered_only_when_they_have_content(self, log_dir):
        (log_dir / "empty.log").write_text("")
        watcher = make_watcher(log_dir)
        watcher.poll()
        assert watcher.aggregator.summary().files_processed == 2


class TestPartialLines:
    def test_a_line_without_a_newline_is_held_back(self, tmp_path):
        path = tmp_path / "p.log"
        path.write_text("2026-08-23T10:00:00 INFO complete\n2026-08-23T10:00:01 ERR")
        watcher = make_watcher(tmp_path)

        assert watcher.poll() == 1
        assert watcher.aggregator.malformed_lines == 0

    def test_the_held_back_line_is_completed_on_the_next_poll(self, tmp_path):
        path = tmp_path / "p.log"
        path.write_text("2026-08-23T10:00:00 ERR")
        watcher = make_watcher(tmp_path)
        watcher.poll()

        append(path, "OR partial write finished\n")
        assert watcher.poll() == 1
        parsed = watcher.aggregator
        assert parsed.level_counts == {"ERROR": 1}
        assert parsed.malformed_lines == 0

    def test_flush_pending_ingests_an_unterminated_final_line(self, tmp_path):
        (tmp_path / "p.log").write_text("2026-08-23T10:00:00 INFO no trailing newline")
        watcher = make_watcher(tmp_path)
        watcher.poll()
        assert watcher.aggregator.parsed_lines == 0

        assert watcher.flush_pending() == 1
        assert watcher.aggregator.parsed_lines == 1

    def test_flush_pending_is_idempotent(self, tmp_path):
        (tmp_path / "p.log").write_text("2026-08-23T10:00:00 INFO tail")
        watcher = make_watcher(tmp_path)
        watcher.poll()
        watcher.flush_pending()
        assert watcher.flush_pending() == 0
        assert watcher.aggregator.parsed_lines == 1

    def test_scan_once_reads_the_whole_file_including_the_tail(self, tmp_path):
        (tmp_path / "p.log").write_text(
            "2026-08-23T10:00:00 INFO one\n2026-08-23T10:00:01 INFO two"
        )
        watcher = make_watcher(tmp_path)
        assert watcher.scan_once() == 2
        assert watcher.aggregator.parsed_lines == 2


class TestRotationAndTruncation:
    def test_truncation_to_a_shorter_file_restarts_from_zero(self, tmp_path):
        path = tmp_path / "r.log"
        path.write_text("2026-08-23T10:00:00 INFO a much longer first line\n")
        watcher = make_watcher(tmp_path)
        watcher.poll()

        path.write_text("2026-08-23T11:00:00 WARN short\n")
        assert watcher.poll() == 1
        assert watcher.aggregator.level_counts == {"INFO": 1, "WARNING": 1}

    def test_rewrite_to_a_longer_file_restarts_from_zero(self, tmp_path):
        # Truncate-then-write-more keeps the inode and grows the size, so only
        # the leading-bytes fingerprint can catch it.
        path = tmp_path / "r.log"
        path.write_text("2026-08-23T10:00:00 INFO first\n")
        watcher = make_watcher(tmp_path)
        watcher.poll()

        path.write_text("2026-08-23T11:00:00 WARNING replaced with a longer line\n")
        assert watcher.poll() == 1
        assert watcher.aggregator.level_counts == {"INFO": 1, "WARNING": 1}

    def test_replacement_by_a_new_inode_restarts_from_zero(self, tmp_path):
        path = tmp_path / "r.log"
        path.write_text("2026-08-23T10:00:00 INFO original content here\n" * 3)
        watcher = make_watcher(tmp_path)
        watcher.poll()
        assert watcher.aggregator.parsed_lines == 3

        # Rotate: move the old file aside and drop a new, shorter one in place.
        path.rename(tmp_path / "r.log.1")
        path.write_text("2026-08-23T11:00:00 ERROR brand new file\n")

        watcher.poll()
        assert watcher.aggregator.level_counts["ERROR"] == 1

    def test_growth_without_rotation_does_not_re_read(self, tmp_path):
        path = tmp_path / "r.log"
        path.write_text("2026-08-23T10:00:00 INFO one\n")
        watcher = make_watcher(tmp_path)
        watcher.poll()
        append(path, "2026-08-23T10:00:01 INFO two\n")
        watcher.poll()
        assert watcher.aggregator.parsed_lines == 2


class TestRunLoop:
    def test_runs_the_requested_number_of_iterations(self, log_dir):
        watcher = make_watcher(log_dir)
        calls = []
        iterations = watcher.run(
            interval=0,
            on_poll=lambda n, w: calls.append(n),
            max_iterations=3,
            sleep=lambda _: None,
        )
        assert iterations == 3
        assert calls == [4, 0, 0]

    def test_does_not_sleep_after_the_final_iteration(self, log_dir):
        slept = []
        make_watcher(log_dir).run(
            interval=5, max_iterations=2, sleep=slept.append
        )
        assert slept == [5]

    def test_on_poll_is_optional(self, log_dir):
        assert make_watcher(log_dir).run(
            interval=0, max_iterations=1, sleep=lambda _: None
        ) == 1

    def test_new_content_between_iterations_is_reported(self, log_dir):
        watcher = make_watcher(log_dir)
        seen = []

        def grow(n, _w):
            seen.append(n)
            if len(seen) == 1:
                append(log_dir / "a.log", "2026-08-23T10:09:00 INFO late arrival\n")

        watcher.run(
            interval=0, on_poll=grow, max_iterations=2, sleep=lambda _: None
        )
        assert seen == [4, 1]


class TestUnreadableFiles:
    def test_unreadable_file_is_skipped_not_fatal(self, tmp_path, monkeypatch):
        path = tmp_path / "locked.log"
        path.write_text("2026-08-23T10:00:00 INFO secret\n")
        watcher = make_watcher(tmp_path)

        original_open = Path.open

        def deny(self, *args, **kwargs):
            if self.name == "locked.log":
                raise PermissionError("denied")
            return original_open(self, *args, **kwargs)

        monkeypatch.setattr(Path, "open", deny)
        assert watcher.poll() == 0

    def test_a_file_vanishing_after_discovery_is_skipped(self, tmp_path):
        path = tmp_path / "gone.log"
        path.write_text("2026-08-23T10:00:00 INFO here\n")
        watcher = make_watcher(tmp_path)
        path.unlink()
        # discover() already handed us the path; stat() now fails.
        assert list(watcher._read_new_lines(path)) == []
        assert watcher.aggregator.total_lines == 0

    def test_a_file_vanishing_mid_poll_is_skipped(self, tmp_path, monkeypatch):
        path = tmp_path / "gone.log"
        path.write_text("2026-08-23T10:00:00 INFO here\n")
        watcher = make_watcher(tmp_path)

        original_stat = Path.stat

        def vanish(self, *args, **kwargs):
            if self.name == "gone.log":
                raise FileNotFoundError("gone")
            return original_stat(self, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", vanish)
        # discover() must tolerate the file disappearing under it.
        assert watcher.discover() == []
        assert watcher.poll() == 0
