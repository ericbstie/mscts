#!/usr/bin/env python3
"""Mutation runner: prove a test bites by mutating the code it covers and watching it fail.

Usage:
    python3 scripts/mutate.py [--timeout SECONDS] <file> <old> <new> -- <pytest args...>

Backs up `<file>`, checks that `<old>` occurs in it exactly once, replaces that one
occurrence with `<new>`, runs `uv run pytest <pytest args...>` under a timeout (default
60 s), and always restores `<file>` from the backup: on a normal return, a test
failure, a timeout, or Ctrl-C.

Exit code:
    0   the tests FAILED under the mutation (it was killed: the tests bite).
    1   the tests PASSED under the mutation (it survived: strengthen the tests).
    2   the arguments were bad, or `<old>` did not occur in `<file>` exactly once.
"""

import argparse
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT_S = 60.0
"""How long the pytest run gets before it is killed and counted as a kill."""

_BACKUP_SUFFIX = ".mutate-orig"


class MutateError(Exception):
    """Bad arguments, or `<old>` does not occur in the file exactly once."""


@dataclass(frozen=True, slots=True)
class Args:
    """One parsed invocation: the mutation to apply, and the pytest run to check it with."""

    file: Path
    old: str
    new: str
    pytest_args: tuple[str, ...]
    timeout_s: float


def split_argv(argv: Sequence[str]) -> tuple[list[str], list[str]]:
    """Split `argv` on the first literal "--" into (mutate.py's own args, pytest args).

    Raises:
        MutateError: There is no "--" in `argv`.
    """
    if "--" not in argv:
        msg = "missing the '--' separator before the pytest arguments"
        raise MutateError(msg)
    index = argv.index("--")
    return list(argv[:index]), list(argv[index + 1 :])


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mutate.py", description="Mutate one occurrence in a file, then run pytest."
    )
    parser.add_argument("file", type=Path)
    parser.add_argument("old")
    parser.add_argument("new")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S, dest="timeout_s")
    return parser


def parse_args(argv: Sequence[str]) -> Args:
    """Parse `argv` (without the program name) into `Args`.

    Raises:
        MutateError: There is no "--", or nothing follows it.
        SystemExit: The part before "--" is not `[--timeout SECONDS] <file> <old> <new>`
            (argparse prints the usage message and exits with code 2).
    """
    own, pytest_args = split_argv(argv)
    if not pytest_args:
        msg = "no pytest arguments after '--'"
        raise MutateError(msg)
    parsed = _build_parser().parse_args(own)
    return Args(
        file=parsed.file,
        old=parsed.old,
        new=parsed.new,
        pytest_args=tuple(pytest_args),
        timeout_s=parsed.timeout_s,
    )


def check_single_occurrence(text: str, old: str) -> None:
    """Raise MutateError unless `old` occurs in `text` exactly once."""
    count = text.count(old)
    if count != 1:
        msg = f"{old!r} occurs {count} time(s) in the file; mutate.py needs exactly one"
        raise MutateError(msg)


def mutate_text(text: str, old: str, new: str) -> str:
    """Return `text` with its one occurrence of `old` replaced by `new`."""
    return text.replace(old, new, 1)


def verdict(returncode: int | None) -> int:
    """This tool's own exit code for a pytest run that exited `returncode`.

    `returncode` is None if the run timed out, which counts as a kill: a mutation
    whose tests never finish is not a passing test suite.
    """
    return 0 if returncode is None or returncode != 0 else 1


def backup_path(file: Path) -> Path:
    """Where `apply_mutation` backs up `file`'s original content."""
    return file.with_name(file.name + _BACKUP_SUFFIX)


def apply_mutation(file: Path, backup: Path, old: str, new: str) -> None:
    """Back up `file` to `backup`, then replace its one occurrence of `old` with `new`.

    Raises:
        MutateError: `backup` already exists (a previous run did not clean up: restore
            or remove it first), or `old` does not occur in `file` exactly once. Neither
            case writes to `file`.
    """
    if backup.exists():
        msg = f"{backup} already exists: restore it (or remove it) before mutating again"
        raise MutateError(msg)
    original = file.read_text()
    backup.write_text(original)
    try:
        check_single_occurrence(original, old)
    except MutateError:
        backup.unlink()
        raise
    file.write_text(mutate_text(original, old, new))


def restore(file: Path, backup: Path) -> None:
    """Put `backup`'s content back at `file`, and remove `backup`."""
    file.write_bytes(backup.read_bytes())
    backup.unlink()


def run_pytest(uv: str, pytest_args: Sequence[str], *, timeout_s: float) -> int | None:
    """Run `uv run pytest <pytest_args>`; return its exit code, or None if it timed out."""
    try:
        result = subprocess.run(  # noqa: S603 - a fixed, absolute-path launcher; no shell
            [uv, "run", "pytest", *pytest_args], timeout=timeout_s, check=False
        )
    except subprocess.TimeoutExpired:
        return None
    return result.returncode


def main(argv: Sequence[str] | None = None) -> int:
    """Run the mutation described by `argv` (`sys.argv[1:]` if None); return the exit code."""
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
    except MutateError as exc:
        print(f"mutate.py: {exc}", file=sys.stderr)
        return 2
    uv = shutil.which("uv")
    if uv is None:
        print("mutate.py: no `uv` on PATH", file=sys.stderr)
        return 2
    backup = backup_path(args.file)
    try:
        apply_mutation(args.file, backup, args.old, args.new)
    except MutateError as exc:
        print(f"mutate.py: {exc}", file=sys.stderr)
        return 2
    try:
        returncode = run_pytest(uv, args.pytest_args, timeout_s=args.timeout_s)
    finally:
        restore(args.file, backup)
    outcome = "KILLED" if verdict(returncode) == 0 else "SURVIVED"
    print(f"{outcome} (pytest exit code {returncode})")
    return verdict(returncode)


if __name__ == "__main__":
    sys.exit(main())
