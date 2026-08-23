"""Tests for the command line interface."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from logwatch import __version__
from logwatch.cli import main


@pytest.fixture
def runner() -> CliRunner:
    # Click 8.1 merges stderr into stdout unless asked not to; 8.2+ always
    # keeps them apart. Either way we want them separate, because --json
    # output must stay clean on stdout while status text goes to stderr.
    try:
        return CliRunner(mix_stderr=False)  # type: ignore[call-arg]
    except TypeError:
        return CliRunner()


def stdout(result) -> str:
    """Just the machine-readable stream."""
    return result.stdout


def all_output(result) -> str:
    """Everything the command wrote, whichever stream it went to."""
    return result.stdout + result.stderr


class TestTopLevel:
    def test_help(self, runner):
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Aggregate and summarise" in all_output(result)
        assert "report" in all_output(result)
        assert "watch" in all_output(result)

    def test_short_help_flag(self, runner):
        assert runner.invoke(main, ["-h"]).exit_code == 0

    def test_version(self, runner):
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert __version__ in all_output(result)

    def test_unknown_command_fails(self, runner):
        assert runner.invoke(main, ["nope"]).exit_code != 0


class TestReportCommand:
    def test_reports_on_a_directory(self, runner, log_dir):
        result = runner.invoke(main, ["report", "--dir", str(log_dir)])
        assert result.exit_code == 0
        assert "Lines processed   : 4" in all_output(result)
        assert "Files processed   : 2" in all_output(result)

    def test_short_flags(self, runner, log_dir):
        result = runner.invoke(main, ["report", "-d", str(log_dir), "-n", "2"])
        assert result.exit_code == 0
        assert "Top 2 keywords" in all_output(result)

    def test_json_output(self, runner, log_dir):
        result = runner.invoke(main, ["report", "--dir", str(log_dir), "--json"])
        assert result.exit_code == 0
        data = json.loads(stdout(result))
        assert data["parsed_lines"] == 4
        assert data["level_counts"]["INFO"] == 2

    def test_top_limit_is_applied_to_json(self, runner, log_dir):
        result = runner.invoke(
            main, ["report", "-d", str(log_dir), "--json", "-n", "1"]
        )
        assert len(json.loads(stdout(result))["top_keywords"]) == 1

    def test_pattern_option(self, runner, log_dir):
        result = runner.invoke(
            main, ["report", "-d", str(log_dir), "--pattern", "*.txt", "--json"]
        )
        assert json.loads(stdout(result))["parsed_lines"] == 1

    def test_recursive_option(self, runner, log_dir):
        nested = log_dir / "sub"
        nested.mkdir()
        (nested / "c.log").write_text("2026-08-23T10:00:09 INFO nested line\n")

        flat = runner.invoke(main, ["report", "-d", str(log_dir), "--json"])
        deep = runner.invoke(
            main, ["report", "-d", str(log_dir), "--recursive", "--json"]
        )
        assert json.loads(stdout(flat))["parsed_lines"] == 4
        assert json.loads(stdout(deep))["parsed_lines"] == 5

    def test_min_keyword_length_option(self, runner, log_dir):
        result = runner.invoke(
            main,
            ["report", "-d", str(log_dir), "--json", "--min-keyword-length", "7"],
        )
        keywords = [k["keyword"] for k in json.loads(stdout(result))["top_keywords"]]
        assert all(len(word) >= 7 for word in keywords)

    def test_missing_directory_is_an_error(self, runner, tmp_path):
        result = runner.invoke(main, ["report", "--dir", str(tmp_path / "absent")])
        assert result.exit_code != 0
        assert "does not exist" in all_output(result)

    def test_a_file_instead_of_a_directory_is_an_error(self, runner, log_dir):
        result = runner.invoke(main, ["report", "--dir", str(log_dir / "a.log")])
        assert result.exit_code != 0

    def test_empty_directory_warns_but_succeeds(self, runner, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        result = runner.invoke(main, ["report", "--dir", str(empty)])
        assert result.exit_code == 0
        assert "No files matching" in all_output(result)
        assert "(no log lines parsed)" in all_output(result)

    def test_negative_top_is_rejected(self, runner, log_dir):
        result = runner.invoke(main, ["report", "-d", str(log_dir), "-n", "-1"])
        assert result.exit_code != 0

    def test_unterminated_final_line_is_included(self, runner, tmp_path):
        (tmp_path / "t.log").write_text("2026-08-23T10:00:00 INFO no newline at eof")
        result = runner.invoke(main, ["report", "-d", str(tmp_path), "--json"])
        assert json.loads(stdout(result))["parsed_lines"] == 1


class TestWatchCommand:
    def test_bounded_run_prints_a_final_report(self, runner, log_dir):
        result = runner.invoke(
            main,
            ["watch", "-d", str(log_dir), "--iterations", "1", "--interval", "0.05"],
        )
        assert result.exit_code == 0
        assert "Watching" in all_output(result)
        assert "Final report:" in all_output(result)
        assert "Lines processed   : 4" in all_output(result)

    def test_quiet_suppresses_per_poll_reports(self, runner, log_dir):
        noisy = runner.invoke(
            main,
            ["watch", "-d", str(log_dir), "--iterations", "1", "--interval", "0.05"],
        )
        quiet = runner.invoke(
            main,
            [
                "watch",
                "-d",
                str(log_dir),
                "--iterations",
                "1",
                "--interval",
                "0.05",
                "--quiet",
            ],
        )
        assert all_output(noisy).count("logwatch report") == 2
        assert all_output(quiet).count("logwatch report") == 1

    def test_json_mode(self, runner, log_dir):
        result = runner.invoke(
            main,
            [
                "watch",
                "-d",
                str(log_dir),
                "--iterations",
                "1",
                "--interval",
                "0.05",
                "--quiet",
                "--json",
            ],
        )
        assert result.exit_code == 0
        assert json.loads(stdout(result))["parsed_lines"] == 4

    def test_missing_directory_is_an_error(self, runner, tmp_path):
        result = runner.invoke(main, ["watch", "--dir", str(tmp_path / "absent")])
        assert result.exit_code != 0

    def test_interval_must_be_positive(self, runner, log_dir):
        result = runner.invoke(
            main, ["watch", "-d", str(log_dir), "--interval", "0", "--iterations", "1"]
        )
        assert result.exit_code != 0

    def test_iterations_must_be_at_least_one(self, runner, log_dir):
        result = runner.invoke(
            main, ["watch", "-d", str(log_dir), "--iterations", "0"]
        )
        assert result.exit_code != 0

    def test_keyboard_interrupt_still_prints_a_report(
        self, runner, log_dir, monkeypatch
    ):
        from logwatch.watcher import DirectoryWatcher

        def interrupt(self, *args, **kwargs):
            self.poll()
            raise KeyboardInterrupt

        monkeypatch.setattr(DirectoryWatcher, "run", interrupt)
        result = runner.invoke(
            main, ["watch", "-d", str(log_dir), "--interval", "0.05"]
        )
        assert result.exit_code == 0
        assert "Final report:" in all_output(result)
        assert "Lines processed   : 4" in all_output(result)


class TestDefaultDirectory:
    def test_report_defaults_to_the_logs_directory(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as cwd:
            from pathlib import Path

            logs = Path(cwd) / "logs"
            logs.mkdir()
            (logs / "d.log").write_text("2026-08-23T10:00:00 INFO default dir\n")

            result = runner.invoke(main, ["report", "--json"])
            assert result.exit_code == 0
            assert json.loads(stdout(result))["parsed_lines"] == 1
