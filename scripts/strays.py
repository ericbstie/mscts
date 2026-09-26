#!/usr/bin/env python3
r"""List stray processes: leftovers a leak-guarded test or a worker session should not have.

Usage:
    python3 scripts/strays.py <pattern>

Lists every running process whose argv matches the regex `<pattern>`, read straight
from /proc, one per line as "<pid>\t<argv...>". Exits non-zero if any are found.

`<pattern>` inevitably appears in this tool's own argv (and in the argv of whatever
shell wrapper launched it: the harness runs a command as `sh -c "<the command
line>"`, and that line names the very pattern being searched for). `pgrep -af`
matches those, giving a false positive on every run. This tool excludes itself and
every one of its ancestors instead, so it only ever reports a real, separate
process — never itself or the wrapper that started it.
"""

import argparse
import os
import re
import sys
from collections.abc import Callable, Iterable
from collections.abc import Set as AbstractSet
from pathlib import Path

DEFAULT_PROC = Path("/proc")
_ANCESTOR_LIMIT = 4096
"""A defensive bound on the ancestor walk, well past any real process tree depth."""


def all_pids(proc_dir: Path = DEFAULT_PROC) -> list[int]:
    """Every pid currently in `proc_dir` (a moment-in-time snapshot)."""
    return sorted(int(entry.name) for entry in proc_dir.iterdir() if entry.name.isdigit())


def read_cmdline(pid: int, proc_dir: Path = DEFAULT_PROC) -> list[str] | None:
    """`pid`'s argv, or None if it has already gone (or cannot be read)."""
    try:
        data = (proc_dir / str(pid) / "cmdline").read_bytes()
    except OSError:
        return None
    return [part.decode(errors="replace") for part in data.split(b"\0") if part]


def read_ppid(pid: int, proc_dir: Path = DEFAULT_PROC) -> int | None:
    """`pid`'s parent pid, or None if it has already gone (or cannot be read).

    /proc/<pid>/stat is `pid (comm) state ppid ...`; comm can itself contain
    spaces or parentheses, so this splits after the *last* `)`, where state and
    ppid are always the first two fields, whatever comm held.
    """
    try:
        text = (proc_dir / str(pid) / "stat").read_text()
    except OSError:
        return None
    fields = text.rpartition(")")[2].split()
    min_fields = 2  # state, ppid
    if len(fields) < min_fields:
        return None
    try:
        return int(fields[1])
    except ValueError:
        return None


def ancestors(
    pid: int, *, ppid_of: Callable[[int], int | None], limit: int = _ANCESTOR_LIMIT
) -> set[int]:
    """Every ancestor of `pid`: its parent, grandparent, ..., up to and including PID 1.

    Stops (without adding it) at a parent that cannot be read, is PID 0 (not a real
    process: the kernel's placeholder for "no parent"), or has already been visited
    in this walk (including `pid` itself) — a defensive guard against a cycle,
    which a real kernel's process tree never has.
    """
    visited = {pid}
    found: set[int] = set()
    current = pid
    for _ in range(limit):
        parent = ppid_of(current)
        if parent is None or parent == 0 or parent in visited:
            return found
        found.add(parent)
        visited.add(parent)
        if parent == 1:
            return found
        current = parent
    return found


def find_strays(
    pids: Iterable[int],
    pattern: re.Pattern[str],
    *,
    exclude: AbstractSet[int],
    cmdline_of: Callable[[int], list[str] | None],
) -> list[tuple[int, list[str]]]:
    """Every pid in `pids`, not in `exclude`, whose argv matches `pattern`.

    Matches against the argv tokens joined with a space, like `ps`/`pgrep -f`.
    A pid whose cmdline cannot be read (it has already gone) is skipped, not
    reported.
    """
    strays: list[tuple[int, list[str]]] = []
    for pid in pids:
        if pid in exclude:
            continue
        argv = cmdline_of(pid)
        if argv is not None and pattern.search(" ".join(argv)):
            strays.append((pid, argv))
    return strays


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="strays.py", description="List processes whose argv matches a pattern."
    )
    parser.add_argument("pattern", help="a regex, matched against each process's joined argv")
    return parser


def main(argv: list[str] | None = None) -> int:
    """List the strays matching `argv[0]` (`sys.argv[1:]` if None); return the exit code."""
    args = _build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    pattern = re.compile(args.pattern)
    own_pid = os.getpid()
    exclude = {own_pid, *ancestors(own_pid, ppid_of=read_ppid)}
    strays = find_strays(all_pids(), pattern, exclude=exclude, cmdline_of=read_cmdline)
    for pid, cmd in strays:
        print(f"{pid}\t{' '.join(cmd)}")
    if strays:
        print(f"{len(strays)} stray process(es) matching {args.pattern!r}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
