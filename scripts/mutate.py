#!/usr/bin/env python3
"""Mutation runner: prove a test bites by mutating the code it covers and watching it fail.

Usage:
    python3 scripts/mutate.py [--timeout SECONDS] <file> <old> <new> -- <pytest args...>

Backs up `<file>`, checks that `<old>` occurs in it exactly once, replaces that one
occurrence with `<new>`, runs `uv run pytest <pytest args...>` under a timeout (default
60 s), and always restores `<file>` from the backup: on a normal return, a test
failure, a timeout, or Ctrl-C.

The verdict is KILLED only when pytest actually ran the selection and at least one test
FAILED (exit code 1): that is the only outcome that proves the tests bite. A timeout, or
any other pytest exit code -- 2 (interrupted), 3 (internal error), 4 (usage error, e.g. a
mistyped path) or 5 (no tests collected) -- is INVALID: pytest did not cleanly pass or
fail the selection, so neither KILLED nor SURVIVED can be trusted from it (see MD6,
docs/audits/2026-09-26-foundation.md).

Exit code:
    0   KILLED: pytest ran the selection and at least one test failed.
    1   SURVIVED: pytest ran the selection and every test passed.
    2   the arguments were bad, `<old>` did not occur in `<file>` exactly once, or `uv`
        is not on PATH.
    3   INVALID: the pytest run proves neither KILLED nor SURVIVED (see above).
"""

import argparse
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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


_PYTEST_EXIT_MESSAGES: dict[int, str] = {
    2: "pytest was interrupted (exit code 2)",
    3: "pytest hit an internal error (exit code 3)",
    4: "pytest usage error, e.g. a mistyped path or option (exit code 4)",
    5: "no tests were collected (exit code 5)",
}


@dataclass(frozen=True, slots=True)
class Outcome:
    """This tool's verdict on one mutation: KILLED, SURVIVED, or no verdict (INVALID)."""

    kind: Literal["KILLED", "SURVIVED", "INVALID"]
    detail: str


def classify(returncode: int | None) -> Outcome:
    """Classify a pytest exit code (None on a timeout) as this tool's own `Outcome`.

    KILLED only when pytest actually ran the selection and at least one test failed
    (exit code 1): that is the only outcome that proves the tests bite. SURVIVED when it
    ran and every test passed (exit code 0). Anything else is INVALID: a timeout, or
    pytest exit code 2 (interrupted), 3 (internal error), 4 (usage error) or 5 (no tests
    collected) all mean pytest did not cleanly pass or fail the selection, so no verdict
    can be trusted from it (MD6, docs/audits/2026-09-26-foundation.md).
    """
    if returncode == 1:
        return Outcome("KILLED", "pytest ran and at least one test failed (exit code 1)")
    if returncode == 0:
        return Outcome("SURVIVED", "pytest ran and every test passed (exit code 0)")
    if returncode is None:
        return Outcome("INVALID", "pytest did not finish before the timeout")
    message = _PYTEST_EXIT_MESSAGES.get(returncode, f"unexpected pytest exit code {returncode}")
    return Outcome("INVALID", message)


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


_EXIT_BY_KIND: dict[str, int] = {"KILLED": 0, "SURVIVED": 1, "INVALID": 3}
_EXIT_BAD_ARGS = 2


@dataclass(frozen=True, slots=True)
class Mutation:
    """One `old` -> `new` replacement to try in `file`."""

    file: Path
    old: str
    new: str


def run_mutation(
    mutation: Mutation,
    pytest_args: Sequence[str],
    *,
    timeout_s: float,
    run: Callable[[Sequence[str], float], int | None],
) -> Outcome:
    """Apply `mutation`, run it, always restore, and classify the result.

    `run(pytest_args, timeout_s)` executes the pytest selection and returns its exit code
    (None on a timeout). Real use passes a `uv run pytest` subprocess call; tests inject a
    fake, so every exit code `classify` distinguishes is pinned without spawning pytest.

    Raises:
        MutateError: `mutation.old` does not occur in `mutation.file` exactly once, or a
            backup from a previous, uncleaned run already exists. Neither case runs `run`
            or touches `mutation.file`.
    """
    backup = backup_path(mutation.file)
    apply_mutation(mutation.file, backup, mutation.old, mutation.new)
    try:
        returncode = run(pytest_args, timeout_s)
    finally:
        restore(mutation.file, backup)
    return classify(returncode)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the mutation described by `argv` (`sys.argv[1:]` if None); return the exit code."""
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
    except MutateError as exc:
        print(f"mutate.py: {exc}", file=sys.stderr)
        return _EXIT_BAD_ARGS
    uv = shutil.which("uv")
    if uv is None:
        print("mutate.py: no `uv` on PATH", file=sys.stderr)
        return _EXIT_BAD_ARGS

    def run(pytest_args: Sequence[str], timeout_s: float) -> int | None:
        return run_pytest(uv, pytest_args, timeout_s=timeout_s)

    mutation = Mutation(args.file, args.old, args.new)
    try:
        outcome = run_mutation(mutation, args.pytest_args, timeout_s=args.timeout_s, run=run)
    except MutateError as exc:
        print(f"mutate.py: {exc}", file=sys.stderr)
        return _EXIT_BAD_ARGS
    print(f"{outcome.kind}: {outcome.detail}")
    return _EXIT_BY_KIND[outcome.kind]


if __name__ == "__main__":
    sys.exit(main())
