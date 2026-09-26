#!/usr/bin/env python3
"""Flake hunter: run a pytest selection N times, optionally under CPU stress.

Usage:
    python3 scripts/repeat.py [--times N] [--stress] [--stress-workers N] -- <pytest args...>

Runs `uv run pytest <pytest args...>` `--times` times in a row (default 1). With
`--stress`, before the first run it spawns `--stress-workers` (default `os.cpu_count()`,
i.e. `nproc`) busy-loop processes to load every CPU, and always kills them afterwards --
on a normal return, an exception, or Ctrl-C -- using the leak-guard pattern (Worker
contract, docs/PROCESS.md; see also `tests/support/leak_guard.py`): each stress
process's environment carries a token unique to this invocation, and cleanup SIGKILLs
anything still tagged with it after asking nicely first.

Prints one line per run and a final report: how many runs passed, how many failed, and
the union of failing test ids (from pytest's "FAILED <id> - ..." summary lines) across
every run. Exit code is 0 only if every run passed; a run that failed for any reason
(including a pytest exit code that is not 0 or 1, e.g. an internal error) counts as
failed.
"""

import argparse
import contextlib
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

type Run = Callable[[str, Sequence[str]], tuple[int, frozenset[str]]]

_BUSY_LOOP = "\nwhile True:\n    pass\n"
_STRESS_TOKEN_NAME = "MSCTS_REPEAT_STRESS"  # noqa: S105 - an env var name, not a secret
_STOP_GRACE_S = 2.0  # a busy loop never checks anything, so this is really "give up and kill"
_PROC = Path("/proc")


def tagged_pids(token: str, *, proc_dir: Path = _PROC) -> list[int]:
    """Running processes whose environment holds `token` (an exact "NAME=value" entry).

    A copy of the leak-guard pattern (`tests/support/leak_guard.py`, Worker contract,
    docs/PROCESS.md): duplicated rather than imported, since `scripts/` runs standalone
    (by path, not as part of the `tests` package `ty` and pytest's importlib mode see).
    """
    needle = token.encode()
    pids = []
    for entry in proc_dir.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            environ = (entry / "environ").read_bytes()  # empty for a zombie
        except OSError:  # gone meanwhile
            continue
        if needle in environ.split(b"\0"):
            pids.append(int(entry.name))
    return pids


def kill_survivors(token: str, *, within: float = 1.0, proc_dir: Path = _PROC) -> list[int]:
    """SIGKILL every process still tagged with `token` after `within` seconds; return them."""
    deadline = time.monotonic() + within
    leaked = tagged_pids(token, proc_dir=proc_dir)
    while leaked and time.monotonic() < deadline:
        time.sleep(0.01)
        leaked = tagged_pids(token, proc_dir=proc_dir)
    for pid in leaked:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
    return leaked


class RepeatError(Exception):
    """Bad arguments: no "--" separator, no pytest arguments, or a non-positive count."""


@dataclass(frozen=True, slots=True)
class Args:
    """One parsed invocation: how many times to run, the stress setting, and pytest's args."""

    pytest_args: tuple[str, ...]
    times: int
    stress: bool
    stress_workers: int


def split_argv(argv: Sequence[str]) -> tuple[list[str], list[str]]:
    """Split `argv` on the first literal "--" into (repeat.py's own args, pytest args).

    Raises:
        RepeatError: There is no "--" in `argv`.
    """
    if "--" not in argv:
        msg = "missing the '--' separator before the pytest arguments"
        raise RepeatError(msg)
    index = argv.index("--")
    return list(argv[:index]), list(argv[index + 1 :])


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repeat.py", description="Run a pytest selection N times, optionally under CPU stress."
    )
    parser.add_argument("--times", type=int, default=1, help="how many times to run (default 1)")
    parser.add_argument(
        "--stress", action="store_true", help="load every CPU with busy loops while running"
    )
    parser.add_argument(
        "--stress-workers",
        type=int,
        default=None,
        help="how many busy-loop processes (default: os.cpu_count(), i.e. nproc)",
    )
    return parser


def parse_args(argv: Sequence[str]) -> Args:
    """Parse `argv` (without the program name) into `Args`.

    Raises:
        RepeatError: There is no "--", nothing follows it, `--times` is not a positive
            integer, or `--stress-workers` is given but not a positive integer.
        SystemExit: The part before "--" does not otherwise parse (argparse prints the
            usage message and exits with code 2).
    """
    own, pytest_args = split_argv(argv)
    if not pytest_args:
        msg = "no pytest arguments after '--'"
        raise RepeatError(msg)
    parsed = _build_parser().parse_args(own)
    if parsed.times < 1:
        msg = "--times must be at least 1"
        raise RepeatError(msg)
    workers = parsed.stress_workers
    if workers is not None and workers < 1:
        msg = "--stress-workers must be at least 1"
        raise RepeatError(msg)
    if workers is None:
        workers = os.cpu_count() or 1
    return Args(
        pytest_args=tuple(pytest_args),
        times=parsed.times,
        stress=parsed.stress,
        stress_workers=workers,
    )


@contextlib.contextmanager
def stress_load(
    count: int, token: str, *, python: str = sys.executable
) -> Iterator[list[subprocess.Popen[bytes]]]:
    """Load every CPU: spawn `count` busy-loop processes tagged with `token` for the duration.

    `token` is a bare value (not "NAME=value"); every spawned process's environment holds
    `MSCTS_REPEAT_STRESS=<token>`. However the `with` block ends -- return, exception, or
    Ctrl-C -- every process is asked to terminate, then given `_STOP_GRACE_S` to exit, then
    SIGKILLed; `kill_survivors` (the leak-guard pattern) sweeps `/proc` once more
    afterwards, so a process this function itself could not reap (e.g. it was
    reparented) is still cleaned up before this returns.
    """
    env = {**os.environ, _STRESS_TOKEN_NAME: token}
    processes = [
        subprocess.Popen(  # noqa: S603 - a fixed, absolute-path launcher; no shell
            [python, "-I", "-S", "-c", _BUSY_LOOP], env=env
        )
        for _ in range(count)
    ]
    try:
        yield processes
    finally:
        for process in processes:
            process.terminate()
        deadline = time.monotonic() + _STOP_GRACE_S
        for process in processes:
            remaining = max(0.0, deadline - time.monotonic())
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=remaining)
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
        kill_survivors(f"{_STRESS_TOKEN_NAME}={token}")


def failing_ids_in(stdout: str) -> frozenset[str]:
    """The test ids named in pytest's "FAILED <id> - ..." short summary lines in `stdout`."""
    ids: set[str] = set()
    for line in stdout.splitlines():
        if line.startswith("FAILED "):
            ids.add(line.removeprefix("FAILED ").split(" - ", 1)[0].strip())
    return frozenset(ids)


def run_once(uv: str, pytest_args: Sequence[str]) -> tuple[int, frozenset[str]]:
    """Run `uv run pytest <pytest_args>` once; return (exit code, failing test ids)."""
    result = subprocess.run(  # noqa: S603 - a fixed, absolute-path launcher; no shell
        [uv, "run", "pytest", *pytest_args], capture_output=True, text=True, check=False
    )
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode, failing_ids_in(result.stdout)


@dataclass(frozen=True, slots=True)
class RepeatResult:
    """The outcome of running a selection `times` times: how many passed, how many failed."""

    times: int
    passed: int
    failed: int
    failing_ids: frozenset[str]


def run_repeats(
    uv: str, pytest_args: Sequence[str], times: int, *, run: Run = run_once
) -> RepeatResult:
    """Run `pytest_args` `times` times with `uv`; return the aggregated `RepeatResult`.

    `run` is `run_once` by default; tests inject a fake with the same signature so the
    aggregation logic is pinned without spawning real pytest processes.
    """
    passed = 0
    failed = 0
    failing_ids: set[str] = set()
    for index in range(times):
        returncode, ids = run(uv, pytest_args)
        print(f"run {index + 1}/{times}: exit code {returncode}, {len(ids)} failing")
        if returncode == 0:
            passed += 1
        else:
            failed += 1
            failing_ids |= ids
    return RepeatResult(
        times=times, passed=passed, failed=failed, failing_ids=frozenset(failing_ids)
    )


def print_report(result: RepeatResult) -> int:
    """Print `result`'s summary; return the exit code (0 only if every run passed)."""
    print(f"{result.times} run(s): {result.passed} passed, {result.failed} failed")
    if result.failing_ids:
        print("failing test ids:")
        for test_id in sorted(result.failing_ids):
            print(f"  {test_id}")
    return 0 if result.failed == 0 else 1


def main(argv: Sequence[str] | None = None) -> int:
    """Run what `argv` describes (`sys.argv[1:]` if None); return the exit code."""
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
    except RepeatError as exc:
        print(f"repeat.py: {exc}", file=sys.stderr)
        return 2
    uv = shutil.which("uv")
    if uv is None:
        print("repeat.py: no `uv` on PATH", file=sys.stderr)
        return 2
    if args.stress:
        token = uuid.uuid4().hex
        with stress_load(args.stress_workers, token):
            result = run_repeats(uv, args.pytest_args, args.times)
    else:
        result = run_repeats(uv, args.pytest_args, args.times)
    return print_report(result)


if __name__ == "__main__":
    sys.exit(main())
