#!/usr/bin/env python3
r"""Wait, for a bounded time, until a file exists or a log line matches.

Usage:
    python3 scripts/wait_for.py FILE [--pattern REGEX] [--timeout S]

Polls FILE once a second. Without `--pattern` it waits until FILE exists (an rc file
that a detached run writes last) and prints `found FILE: <its first line>`. With
`--pattern` it waits until some line of FILE matches the regex and prints the first
such line, grep style: `FILE:<line number>:<line>`.

`--timeout` is in seconds and defaults to 580, under the Bash tool's 10-minute limit
and the Worker contract's 590 s per poll. Exit code 0: found. 1: timed out, and stderr
says what it waited for (poll again in another Bash call). 2: bad arguments.

Use it in place of an `until` loop of your own, one Bash call per poll:

    python3 scripts/wait_for.py /abs/run.rc
    python3 scripts/wait_for.py /abs/run.log --pattern 'Done \('
"""

import argparse
import re
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

DEFAULT_TIMEOUT = 580.0
"""Seconds. Under the Bash tool's 10-minute limit, with room for the interpreter's start."""

POLL_INTERVAL = 1.0


def find_in(path: Path, pattern: re.Pattern[str] | None) -> str | None:
    """What `path` holds that the wait is for, or None if it is not there yet.

    No pattern: the file's existence, with its first line if it has one. A pattern: the
    first line that matches, as `path:number:line`. A file that vanishes or cannot be read
    is not there yet.
    """
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return None
    if pattern is None:
        return f"found {path}: {lines[0]}" if lines else f"found {path}"
    for number, line in enumerate(lines, start=1):
        if pattern.search(line):
            return f"{path}:{number}:{line}"
    return None


def wait(
    check: Callable[[], str | None],
    *,
    timeout: float,
    interval: float,
    now: Callable[[], float],
    sleep: Callable[[float], None],
) -> str | None:
    """Call `check` until it returns something, or until `timeout` seconds have passed.

    Checks once more at the deadline. Returns what `check` found, or None on timeout.
    """
    deadline = now() + timeout
    while True:
        found = check()
        if found is not None:
            return found
        remaining = deadline - now()
        if remaining <= 0:
            return None
        sleep(min(interval, remaining))


def _pattern(text: str) -> re.Pattern[str]:
    try:
        return re.compile(text)
    except re.error as exc:
        msg = f"not a regex: {exc}"
        raise argparse.ArgumentTypeError(msg) from exc


def _seconds(text: str) -> float:
    try:
        seconds = float(text)
    except ValueError as exc:
        msg = f"not a number: {text!r}"
        raise argparse.ArgumentTypeError(msg) from exc
    if seconds < 0:
        msg = "must not be negative"
        raise argparse.ArgumentTypeError(msg)
    return seconds


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wait_for.py", description="Wait until a file exists or a log line matches."
    )
    parser.add_argument("file", type=Path, help="the file to wait for")
    parser.add_argument(
        "--pattern",
        type=_pattern,
        default=None,
        help="wait until a line of FILE matches this regex (default: until FILE exists)",
    )
    parser.add_argument(
        "--timeout",
        type=_seconds,
        default=DEFAULT_TIMEOUT,
        metavar="S",
        help=f"give up after S seconds (default {DEFAULT_TIMEOUT:g})",
    )
    return parser


def _waited_for(path: Path, pattern: re.Pattern[str] | None) -> str:
    if pattern is None:
        return str(path)
    return f"{path} to match {pattern.pattern!r}"


def main(argv: Sequence[str] | None = None) -> int:
    """Wait as `argv` (`sys.argv[1:]` if None) says; return the exit code."""
    args = _build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    found = wait(
        lambda: find_in(args.file, args.pattern),
        timeout=args.timeout,
        interval=POLL_INTERVAL,
        now=time.monotonic,
        sleep=time.sleep,
    )
    if found is None:
        waited = _waited_for(args.file, args.pattern)
        print(f"timed out after {args.timeout:g} s waiting for {waited}", file=sys.stderr)
        return 1
    print(found)
    return 0


if __name__ == "__main__":
    sys.exit(main())
