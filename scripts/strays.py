#!/usr/bin/env python3
r"""List stray processes: leftovers a leak-guarded test or a worker session should not have.

Usage:
    python3 scripts/strays.py <pattern> [--token NAME=value] [--cwd PREFIX]

Lists every running process whose argv matches the regex `<pattern>`, read straight
from /proc, one per line as "<pid>\t<argv...>". Exits non-zero if any are found.

`<pattern>` inevitably appears in this tool's own argv (and in the argv of whatever
shell wrapper launched it: the harness runs a command as `sh -c "<the command
line>"`, and that line names the very pattern being searched for). `pgrep -af`
matches those, giving a false positive on every run. This tool excludes itself and
every one of its ancestors instead, so it only ever reports a real, separate
process — never itself or the wrapper that started it.

`--token NAME=value` narrows the match further to processes whose `/proc/<pid>/environ`
holds that exact `NAME=value` entry, and `--cwd PREFIX` to processes whose
`/proc/<pid>/cwd` resolves under `PREFIX`. Both combine with `<pattern>` (and with each
other) by AND: a plain pattern like `server.jar` can otherwise match another worker's
live vanilla Instance running the same jar; the Worker contract's leak-guard token, or
the test's own workdir, tells them apart.
"""

import argparse
import os
import re
import sys
from collections.abc import Callable, Iterable, Mapping
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


def read_environ(pid: int, proc_dir: Path = DEFAULT_PROC) -> dict[str, str] | None:
    """`pid`'s environment as a dict, or None if it cannot be read (gone, or no permission).

    `/proc/<pid>/environ` is NUL-separated `NAME=value` entries; an entry with no `=` (should
    not happen on a real kernel) is skipped rather than raising.
    """
    try:
        data = (proc_dir / str(pid) / "environ").read_bytes()
    except OSError:
        return None
    environ: dict[str, str] = {}
    for entry in data.split(b"\0"):
        if not entry:
            continue
        text = entry.decode(errors="replace")
        name, sep, value = text.partition("=")
        if sep:
            environ[name] = value
    return environ


def has_token(environ: Mapping[str, str] | None, name: str, value: str) -> bool:
    """True iff `environ` (from `read_environ`) has exactly `name=value`.

    False (never raises) when `environ` is None: an unreadable process is not a match.
    """
    return environ is not None and environ.get(name) == value


def read_cwd(pid: int, proc_dir: Path = DEFAULT_PROC) -> Path | None:
    """`pid`'s current working directory, or None if it cannot be read (gone, or no permission)."""
    try:
        return (proc_dir / str(pid) / "cwd").readlink()
    except OSError:
        return None


def is_under(path: Path | None, prefix: Path) -> bool:
    """True iff `path` is `prefix` itself or somewhere inside it.

    False (never raises) when `path` is None: an unreadable process is not a match.
    """
    if path is None:
        return False
    try:
        path.relative_to(prefix)
    except ValueError:
        return False
    return True


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
    extra_ok: Callable[[int], bool] | None = None,
) -> list[tuple[int, list[str]]]:
    """Every pid in `pids`, not in `exclude`, whose argv matches `pattern`.

    Matches against the argv tokens joined with a space, like `ps`/`pgrep -f`.
    A pid whose cmdline cannot be read (it has already gone) is skipped, not
    reported. When `extra_ok` is given (the `--token`/`--cwd` filters), a pid also
    matching `pattern` is only a stray if `extra_ok(pid)` is also true: the filters
    combine with the pattern, and with each other, by AND.
    """
    strays: list[tuple[int, list[str]]] = []
    for pid in pids:
        if pid in exclude:
            continue
        argv = cmdline_of(pid)
        if argv is None or not pattern.search(" ".join(argv)):
            continue
        if extra_ok is not None and not extra_ok(pid):
            continue
        strays.append((pid, argv))
    return strays


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="strays.py", description="List processes whose argv matches a pattern."
    )
    parser.add_argument("pattern", help="a regex, matched against each process's joined argv")
    parser.add_argument(
        "--token",
        default=None,
        metavar="NAME=value",
        help="only processes whose /proc environ has this exact entry",
    )
    parser.add_argument(
        "--cwd",
        default=None,
        dest="cwd_prefix",
        metavar="PREFIX",
        help="only processes whose /proc/<pid>/cwd resolves under PREFIX",
    )
    return parser


def _parse_token(spec: str) -> tuple[str, str]:
    """Split `--token`'s `NAME=value` into `(NAME, value)`.

    Raises:
        ValueError: `spec` has no `=`.
    """
    name, sep, value = spec.partition("=")
    if not sep:
        msg = f"--token must be NAME=value, got {spec!r}"
        raise ValueError(msg)
    return name, value


def _build_extra_ok(
    args: argparse.Namespace, *, proc_dir: Path = DEFAULT_PROC
) -> Callable[[int], bool] | None:
    """The combined `--token`/`--cwd` predicate for `find_strays`, or None if neither was given."""
    checks: list[Callable[[int], bool]] = []
    if args.token is not None:
        name, value = _parse_token(args.token)
        checks.append(lambda pid: has_token(read_environ(pid, proc_dir), name, value))
    if args.cwd_prefix is not None:
        prefix = Path(args.cwd_prefix).resolve()
        checks.append(lambda pid: is_under(read_cwd(pid, proc_dir), prefix))
    if not checks:
        return None
    return lambda pid: all(check(pid) for check in checks)


def _printable(text: str) -> str:
    """Escape control characters, so one process is always exactly one output line."""
    return "".join(char if char.isprintable() else repr(char)[1:-1] for char in text)


def main(argv: list[str] | None = None) -> int:
    """List the strays matching `argv[0]` (`sys.argv[1:]` if None); return the exit code."""
    args = _build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    pattern = re.compile(args.pattern)
    try:
        extra_ok = _build_extra_ok(args)
    except ValueError as exc:
        print(f"strays.py: {exc}", file=sys.stderr)
        return 2
    own_pid = os.getpid()
    exclude = {own_pid, *ancestors(own_pid, ppid_of=read_ppid)}
    strays = find_strays(
        all_pids(), pattern, exclude=exclude, cmdline_of=read_cmdline, extra_ok=extra_ok
    )
    for pid, cmd in strays:
        print(f"{pid}\t{_printable(' '.join(cmd))}")
    if strays:
        print(f"{len(strays)} stray process(es) matching {args.pattern!r}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
