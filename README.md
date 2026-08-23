# logwatch

A small log aggregation service. Point it at a directory of `.log` files and it
tells you how many lines came in at each level and which words show up most
often in the messages.

```
====================================================
logwatch report
====================================================
Files processed   : 5
Lines processed   : 88
  parsed          : 83
  malformed       : 5
  blank (skipped) : 1
Time range        : 2026-08-23T09:57:44
                 -> 2026-08-23T10:04:11

-- Lines by level ----------------------------------
DEBUG           7    8.4%  ##
INFO           43   51.8%  ##########
WARNING        15   18.1%  ####
ERROR          15   18.1%  ####
CRITICAL        2    2.4%  #
AUDIT           1    1.2%  #

-- Top 10 keywords ---------------------------------
 1. job              15
 2. failed           14
 3. completed        13
 4. account          11
 5. request           9
 6. login             8
 7. status            8
 8. connection        7
 9. orders            6
10. pool              6

(204 distinct keywords overall)
====================================================
```

## Log format

Lines are expected to look like `TIMESTAMP LEVEL message`:

```
2026-08-23T10:00:00 ERROR database connection failed
```

The parser is deliberately forgiving and accepts the common variations:

| Variation | Example |
| --- | --- |
| `T` or space separator | `2026-08-23 10:00:00 INFO up` |
| Fractional seconds | `2026-08-23T10:00:00.123 INFO up` |
| Timezone offset or `Z` | `2026-08-23T10:00:00Z INFO up` |
| Date only | `2026-08-23 INFO up` |
| Bracketed fields | `[2026-08-23T10:00:00] [INFO] up` |
| `:` or `-` after the level | `2026-08-23T10:00:00 INFO: up` |
| Level aliases | `WARN`→`WARNING`, `FATAL`/`CRIT`/`PANIC`→`CRITICAL`, `ERR`→`ERROR`, `VERBOSE`→`TRACE` |
| Custom levels | Any all-caps token, e.g. `AUDIT` |

Anything else — a stack trace continuation, a line with no timestamp, an
impossible date like `2026-13-45` — is counted as **malformed** rather than
silently dropped or crashing the run. Blank lines are skipped and counted
separately.

Keywords are extracted from the message text: lower-cased, stripped of
punctuation, with stopwords, tokens shorter than three characters, bare
numbers and long hex identifiers removed.

## Install

Requires Python 3.9+.

```bash
pip install -e ".[dev]"
```

## Usage

### `logwatch report`

Scan a directory once and print a summary.

```bash
logwatch report --dir ./logs
```

```bash
logwatch report --dir ./logs --top 20 --json
```

### `logwatch watch`

Poll a directory and print a fresh report whenever new lines arrive. Only the
bytes appended since the last poll are read, so this stays cheap on large
files. Stops on `Ctrl-C` (or `SIGTERM`) and prints a final report.

```bash
logwatch watch --dir ./logs --interval 5
```

### Options

Both commands accept:

| Option | Default | Meaning |
| --- | --- | --- |
| `-d`, `--dir` | `./logs` | Directory to read `.log` files from |
| `-n`, `--top` | `10` | How many keywords to show |
| `--json` | off | Emit JSON on stdout instead of a text report |
| `--pattern` | `*.log` | Glob used to select files |
| `--recursive` | off | Also search sub-directories |
| `--min-keyword-length` | `3` | Ignore keywords shorter than this |

`watch` additionally accepts `-i/--interval` (seconds between polls),
`--iterations` (stop after N polls, useful in scripts) and `-q/--quiet` (only
print the final report).

Status messages go to stderr and report output goes to stdout, so `--json`
pipes cleanly:

```bash
logwatch report --json | jq '.level_counts'
```

## Docker

### Build

```bash
docker build -t logwatch:local .
```

### Run against a mounted volume

Mount your log directory at `/logs`. Read-only is enough:

```bash
docker run --rm -v "$PWD/logs:/logs:ro" logwatch:local report --dir /logs
```

The default command watches continuously:

```bash
docker run --rm -v "$PWD/logs:/logs:ro" logwatch:local
```

### Pull from GHCR

```bash
docker pull ghcr.io/siwenwu24/logwatch-claude:latest
```

```bash
docker run --rm -v "$PWD/logs:/logs:ro" ghcr.io/siwenwu24/logwatch-claude:latest report --dir /logs
```

The container runs as an unprivileged user (uid 10001), so the mounted files
need to be readable by it.

> **A note on polling.** The watcher polls rather than using inotify/FSEvents,
> because filesystem events are unreliable across Docker bind mounts and
> network filesystems — exactly where this tends to run. It tracks a read
> offset per file and handles rotation (new inode), truncation, and
> truncate-then-rewrite (via a leading-bytes fingerprint). A line caught
> mid-write is held back until its newline arrives, so partial writes are not
> miscounted as malformed.

## Development

Run the tests:

```bash
pytest
```

With coverage:

```bash
pytest --cov=logwatch --cov-report=term-missing
```

### Layout

```
src/logwatch/
  parser.py      one line -> ParsedLine (or None if malformed)
  keywords.py    message text -> normalised keywords
  aggregator.py  accumulates counts, produces a Summary
  report.py      Summary -> text or JSON
  watcher.py     directory polling with per-file read offsets
  cli.py         click commands: report, watch
tests/           unit tests for each of the above
logs/            sample log files
```

Each layer is independently testable: the parser has no I/O, the aggregator
has no formatting, and the watcher takes an aggregator as a collaborator.

## CI

`.github/workflows/ci.yml` runs the test suite on every push and pull request
across Python 3.9–3.13, builds the Docker image, and smoke-tests it against
the sample logs. On a push to `main` it also publishes the image to
`ghcr.io/siwenwu24/logwatch-claude`.

## License

MIT
