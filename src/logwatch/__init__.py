"""logwatch - a small log aggregation service."""

from .aggregator import LogAggregator, Summary
from .parser import ParsedLine, parse_line
from .watcher import DirectoryWatcher

__version__ = "0.1.0"

__all__ = [
    "LogAggregator",
    "Summary",
    "ParsedLine",
    "parse_line",
    "DirectoryWatcher",
    "__version__",
]
