"""Watching a directory of ``.log`` files for new content.

Uses polling rather than filesystem events on purpose: inotify/FSEvents are
unreliable across Docker bind mounts and network filesystems, which is exactly
where this service is meant to run. Polling a directory of log files is cheap
because we only ever read the bytes appended since the last pass.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from .aggregator import LogAggregator

__all__ = ["DirectoryWatcher", "FileCursor"]

#: How many leading bytes of a file we remember to detect in-place rewrites.
FINGERPRINT_BYTES = 64


@dataclass
class FileCursor:
    """How far we have read into one file, and which file that was."""

    offset: int = 0
    inode: Optional[int] = None
    # Bytes after the last newline: an incomplete line still being written.
    pending: str = ""
    # First bytes of the file, used to notice a truncate-and-rewrite that
    # leaves the file the same size or larger.
    head: bytes = b""


@dataclass
class DirectoryWatcher:
    """Incrementally feeds new log lines from a directory into an aggregator."""

    directory: Path
    aggregator: LogAggregator
    pattern: str = "*.log"
    recursive: bool = False
    encoding: str = "utf-8"
    cursors: Dict[str, FileCursor] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.directory = Path(self.directory)

    # -- discovery ---------------------------------------------------------

    def discover(self) -> List[Path]:
        """Return the log files currently present, in a stable order."""
        if not self.directory.is_dir():
            return []
        globber = self.directory.rglob if self.recursive else self.directory.glob
        found = []
        for path in globber(self.pattern):
            try:
                if path.is_file():
                    found.append(path)
            except OSError:
                # The file disappeared between the glob and the stat.
                continue
        return sorted(found)

    # -- reading -----------------------------------------------------------

    def _read_head(self, path: Path) -> bytes:
        """Read the first bytes of a file, for change detection."""
        try:
            with path.open("rb") as handle:
                return handle.read(FINGERPRINT_BYTES)
        except OSError:
            return b""

    def _read_new_lines(self, path: Path) -> Iterable[str]:
        """Yield complete lines appended to ``path`` since the last poll."""
        key = str(path)
        cursor = self.cursors.setdefault(key, FileCursor())

        try:
            stat = path.stat()
        except OSError:
            return []

        # Decide whether this is still the same file we were reading.
        head = self._read_head(path)
        rotated = cursor.inode is not None and stat.st_ino != cursor.inode
        truncated = stat.st_size < cursor.offset
        # A same-size-or-larger rewrite keeps the inode and defeats the size
        # check, so compare the leading bytes as well.
        common = min(len(head), len(cursor.head))
        rewritten = bool(cursor.head) and head[:common] != cursor.head[:common]

        if rotated or truncated or rewritten:
            cursor.offset, cursor.pending = 0, ""
        cursor.inode = stat.st_ino
        cursor.head = head

        if stat.st_size == cursor.offset:
            return []

        try:
            with path.open("r", encoding=self.encoding, errors="replace") as handle:
                handle.seek(cursor.offset)
                chunk = handle.read()
                cursor.offset = handle.tell()
        except OSError:
            return []

        text = cursor.pending + chunk
        # Hold back a trailing partial line until its newline shows up, so a
        # line caught mid-write is not counted as malformed.
        if text.endswith("\n"):
            cursor.pending = ""
        else:
            text, _, cursor.pending = text.rpartition("\n")

        self.aggregator.register_file(path)
        return text.splitlines()

    def poll(self) -> int:
        """Do one pass over the directory. Returns the number of new lines."""
        new_lines = 0
        for path in self.discover():
            for line in self._read_new_lines(path):
                self.aggregator.add_line(line)
                new_lines += 1
        return new_lines

    def flush_pending(self) -> int:
        """Ingest any held-back final lines that never got a newline.

        Call this at the end of a one-shot scan, where a file's last line
        legitimately has no trailing newline.
        """
        count = 0
        for cursor in self.cursors.values():
            if cursor.pending.strip():
                self.aggregator.add_line(cursor.pending)
                count += 1
            cursor.pending = ""
        return count

    def scan_once(self) -> int:
        """Read everything currently available, including unterminated lines."""
        return self.poll() + self.flush_pending()

    # -- main loop ---------------------------------------------------------

    def run(
        self,
        interval: float = 2.0,
        on_poll: Optional[Callable[[int, "DirectoryWatcher"], None]] = None,
        max_iterations: Optional[int] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> int:
        """Poll until interrupted (or until ``max_iterations`` passes).

        ``on_poll`` is called after each pass with the number of new lines.
        ``max_iterations`` and ``sleep`` exist to keep the loop testable.
        """
        iterations = 0
        while max_iterations is None or iterations < max_iterations:
            new_lines = self.poll()
            iterations += 1
            if on_poll is not None:
                on_poll(new_lines, self)
            if max_iterations is not None and iterations >= max_iterations:
                break
            sleep(interval)
        return iterations
