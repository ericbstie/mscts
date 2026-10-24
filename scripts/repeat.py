#!/usr/bin/env python3
"""Flake hunter: run a pytest selection N times, optionally under CPU stress.

Usage:
    uv run scripts/repeat.py [--times N] [--stress] [--stress-workers N] [--live-lock]
        [--stop-at-first-failure [--failure-log FILE]] [--deadline TIME] -- <pytest args...>

A live selection (a Self-check, a reference or candidate test) runs as
`mise exec -- uv run scripts/repeat.py ...`: the Reference needs Java 25, and without
`mise exec` it finds Java 21 and stops with a PrepareError. repeat.py guesses a selection
is live from its paths and `-m` expression (`selfcheck`, `reference`, `candidate`) and
refuses to start under a Java the Reference refuses, naming that form (exit 2). A
Self-check plays `MSCTS_SELFCHECK_REPEAT` times per run (default 3): a 20-play Self-check
needs `MSCTS_SELFCHECK_REPEAT=20` exported, which repeat.py passes through.

Runs `uv run pytest <pytest args...>` `--times` times in a row (default 1). With
`--stress`, before the first run it spawns `--stress-workers` (default `os.cpu_count()`,
i.e. `nproc`) busy-loop processes to load every CPU, and always kills them afterwards --
on a normal return, an exception, or Ctrl-C -- using the leak-guard pattern (Worker
contract, docs/PROCESS.md; see also `tests/support/leak_guard.py`): each stress
process's environment carries a token unique to this invocation, and cleanup SIGKILLs
anything still tagged with it after asking nicely first.

With `--live-lock`, each run takes the live-tier lock (`scripts/live_lock.py`), runs and
releases it, so a short live run that queued meanwhile goes between two runs of the series
(#411). `--stress` then loads the CPUs only while a run holds the lock. Never wrap a live
series in an outer `live_lock.py`: that holds the lock for the whole series.

With `--stop-at-first-failure`, no run starts after a failing one, and that run's whole
output (stdout, then stderr) is kept in `--failure-log` (default `repeat-failure.log` in
the working directory). The final report then says how many of the runs ran.

With `--deadline <ISO 8601 time with a UTC offset>`, no run starts at or after that time,
and the final report says how many of the runs ran. The deadline is absolute, so a series
split by a restart gets the same one by repeating the flag. With `--live-lock` the time is
checked again once the lock is taken, so a run that waited past it does not start. Exit
code 3: the deadline cut the series short and no run failed.

Prints one line per run, which starts with the UTC time the run ended, and a final
report: how many runs passed, how many failed, and the union of failing test ids (from
pytest's "FAILED <id> - ..." summary lines) across every run. Exit code is 0 only if every
run passed; a run that failed for any reason (including a pytest exit code that is not 0
or 1, e.g. an internal error) counts as failed.
"""

import argparse
import contextlib
import functools
import importlib.util
import itertools
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import types
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

type Run = Callable[[str, Sequence[str]], tuple[int, frozenset[str]]]
type InheritingRun = Callable[[str, Sequence[str], Sequence[int]], tuple[int, frozenset[str]]]
type Scope[T] = Callable[[], AbstractContextManager[T]]

_BUSY_LOOP = "\nwhile True:\n    pass\n"
_STRESS_TOKEN_NAME = "MSCTS_REPEAT_STRESS"  # noqa: S105 - an env var name, not a secret
_STOP_GRACE_S = 2.0  # a busy loop never checks anything, so this is really "give up and kill"
_PROC = Path("/proc")
_DEFAULT_FAILURE_LOG = "repeat-failure.log"


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


class DeadlinePassedError(Exception):
    """The deadline came while a run waited for the live lock, so that run did not start."""


@dataclass(frozen=True, slots=True)
class Args:
    """One parsed invocation: how many times to run, the stress setting, and pytest's args."""

    pytest_args: tuple[str, ...]
    times: int
    stress: bool
    stress_workers: int
    live_lock: bool
    stop_at_first_failure: bool
    failure_log: Path
    deadline: datetime | None


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


def _deadline_arg(text: str) -> datetime:
    """An ISO 8601 time with a UTC offset (`2026-10-24T18:00:00Z`), for `--deadline`.

    Raises:
        argparse.ArgumentTypeError: `text` is not an ISO 8601 time, or names no UTC offset
            (a time with none could be read in the wrong zone, and a deadline shared across
            a restart is the point).
    """
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        msg = f"{text!r} is not an ISO 8601 time"
        raise argparse.ArgumentTypeError(msg) from exc
    if moment.tzinfo is None:
        msg = f"{text!r} has no UTC offset: write it like 2026-10-24T18:00:00Z"
        raise argparse.ArgumentTypeError(msg)
    return moment


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
    parser.add_argument(
        "--live-lock",
        action="store_true",
        help="take the live-tier lock for each run, not for the whole series",
    )
    parser.add_argument(
        "--stop-at-first-failure",
        action="store_true",
        help="end the series at the first failing run and keep that run's output in --failure-log",
    )
    parser.add_argument(
        "--failure-log",
        type=Path,
        default=Path(_DEFAULT_FAILURE_LOG),
        help=f"where the failing run's output is kept (default {_DEFAULT_FAILURE_LOG})",
    )
    parser.add_argument(
        "--deadline",
        type=_deadline_arg,
        default=None,
        help="start no run at or after this ISO 8601 time (with a UTC offset: ...T18:00:00Z)",
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
        live_lock=parsed.live_lock,
        stop_at_first_failure=parsed.stop_at_first_failure,
        failure_log=parsed.failure_log,
        deadline=parsed.deadline,
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


def run_once(
    uv: str,
    pytest_args: Sequence[str],
    inherit: Sequence[int] = (),
    *,
    failure_log: Path | None = None,
) -> tuple[int, frozenset[str]]:
    """Run `uv run pytest <pytest_args>` once; return (exit code, failing test ids).

    The run inherits the descriptors in `inherit` (the live lock's, which it keeps if this
    process is killed). If it fails and `failure_log` is given, its whole output (stdout,
    then stderr) is written there.
    """
    result = subprocess.run(  # noqa: S603 - a fixed, absolute-path launcher; no shell
        [uv, "run", "pytest", *pytest_args],
        capture_output=True,
        text=True,
        check=False,
        pass_fds=tuple(inherit),
    )
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    if result.returncode != 0 and failure_log is not None:
        failure_log.write_text(result.stdout + result.stderr, encoding="utf-8")
    return result.returncode, failing_ids_in(result.stdout)


@dataclass(frozen=True, slots=True)
class RepeatResult:
    """The outcome of running a selection up to `times` times.

    `passed + failed` runs ran; `stopped_by` names what ended the series early
    ("first failure", "deadline"), or is empty if every run ran.
    """

    times: int
    passed: int
    failed: int
    failing_ids: frozenset[str]
    stopped_by: str = ""


_LIVE_TIERS = ("reference", "selfcheck", "candidate")
_LIVE_MARKER = re.compile(rf"(?<!not )\b({'|'.join(_LIVE_TIERS)})\b")


def _names_live_path(arg: str) -> bool:
    """Whether `arg` is a test path with a directory or file named for a live tier.

    That is `selfcheck`, `reference` or `candidate`, or a file ending `_reference.py`
    and so on. A bare word (`-k reference`) is not a path.
    """
    if arg.startswith("-") or not ("/" in arg or ".py" in arg):
        return False
    parts = arg.split("::", maxsplit=1)[0].removesuffix(".py").split("/")
    return any(part == tier or part.endswith(f"_{tier}") for part in parts for tier in _LIVE_TIERS)


def is_live_selection(pytest_args: Sequence[str]) -> bool:
    """Whether `pytest_args` name a live tier, by path or by `-m` marker expression.

    A guess from the names: a selection that reaches a live test any other way (a unit
    file with one live test in it) is not recognised.
    """
    if any(_names_live_path(arg) for arg in pytest_args):
        return True
    expressions = [after for before, after in itertools.pairwise(pytest_args) if before == "-m"]
    return any(_LIVE_MARKER.search(expression) for expression in expressions)


def _java_refusal() -> str | None:
    """Why the Reference refuses the Java this process would find, or None if it accepts it.

    Imports `mscts` here, since only a live selection needs it (see `_load_live_lock`).
    """
    from mscts.adapters.base import PrepareError  # noqa: PLC0415
    from mscts.adapters.vanilla import resolve_java  # noqa: PLC0415
    from mscts.target import TARGET  # noqa: PLC0415

    try:
        resolve_java(TARGET)
    except PrepareError as exc:
        return str(exc)
    return None


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class SeriesRules:
    """When a series ends early, and the clock that tells: no rule means it runs `times` runs."""

    stop_at_first_failure: bool = False
    deadline: datetime | None = None
    now: Callable[[], datetime] = field(default=_utc_now)

    def past_deadline(self) -> bool:
        """Whether a run starting now would start at or after the deadline."""
        return self.deadline is not None and self.now() >= self.deadline


def run_repeats(
    uv: str,
    pytest_args: Sequence[str],
    times: int,
    *,
    run: Run = run_once,
    rules: SeriesRules = SeriesRules(),  # noqa: B008 - frozen, so one shared default is safe
) -> RepeatResult:
    """Run `pytest_args` `times` times with `uv`; return the aggregated `RepeatResult`.

    `run` is `run_once` by default; tests inject a fake with the same signature so the
    aggregation logic is pinned without spawning real pytest processes. `rules` can end
    the series early: after a failing run, or when the deadline has come.
    """
    passed = 0
    failed = 0
    failing_ids: set[str] = set()
    stopped_by = ""
    for index in range(times):
        if rules.past_deadline():
            stopped_by = "deadline"
            break
        try:
            returncode, ids = run(uv, pytest_args)
        except DeadlinePassedError:
            stopped_by = "deadline"
            break
        stamp = rules.now().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        print(
            f"[{stamp}] run {index + 1}/{times}: exit code {returncode}, {len(ids)} failing",
            flush=True,
        )
        if returncode == 0:
            passed += 1
            continue
        failed += 1
        failing_ids |= ids
        if rules.stop_at_first_failure:
            stopped_by = "first failure"
            break
    return RepeatResult(
        times=times,
        passed=passed,
        failed=failed,
        failing_ids=frozenset(failing_ids),
        stopped_by=stopped_by,
    )


def locked_run(
    run: InheritingRun,
    *,
    hold: Scope[int | None],
    load: Scope[object],
    rules: SeriesRules = SeriesRules(),  # noqa: B008 - frozen, so one shared default is safe
) -> Run:
    """`run`, but each call holds the live lock, then the CPU load, for that run only (#411).

    The load starts after the lock is taken, so it never runs while the series waits or
    while another run holds the lock. `run` inherits the lock's descriptor, if `hold` has one.

    Raises (from the returned function):
        DeadlinePassedError: The deadline in `rules` passed while the call waited for the lock.
    """

    def run_locked(uv: str, pytest_args: Sequence[str]) -> tuple[int, frozenset[str]]:
        with hold() as descriptor:
            if rules.past_deadline():
                raise DeadlinePassedError
            with load():
                return run(uv, pytest_args, () if descriptor is None else (descriptor,))

    return run_locked


def _tally(result: RepeatResult) -> str:
    """How many runs ran, and how they went: "20 run(s): ..." or "4 of 20 run(s) ran, ..."."""
    counts = f"{result.passed} passed, {result.failed} failed"
    if not result.stopped_by:
        return f"{result.times} run(s): {counts}"
    ran = result.passed + result.failed
    return f"{ran} of {result.times} run(s) ran, stopped at the {result.stopped_by}: {counts}"


def print_report(result: RepeatResult, *, failure_log: Path | None = None) -> int:
    """Print `result`'s summary; return the exit code.

    0 only if every run passed, 1 if a run failed, 3 if the deadline cut the series short.
    If a run failed and `failure_log` is given, the report names the file.
    """
    print(_tally(result))
    if result.failed and failure_log is not None:
        print(f"output of the failing run: {failure_log}")
    if result.failing_ids:
        print("failing test ids:")
        for test_id in sorted(result.failing_ids):
            print(f"  {test_id}")
    if result.failed:
        return 1
    return 3 if result.stopped_by else 0


def _load_live_lock() -> types.ModuleType:
    """Import `live_lock.py` beside this file: it needs `mscts`, so only `--live-lock` loads it."""
    path = Path(__file__).with_name("live_lock.py")
    spec = importlib.util.spec_from_file_location("live_lock", path)
    if spec is None or spec.loader is None:
        raise ImportError(str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _each_run_load(args: Args) -> Scope[object]:
    """The CPU load of one run: `--stress-workers` busy loops, or nothing without `--stress`."""
    if not args.stress:
        return contextlib.nullcontext

    def load() -> AbstractContextManager[object]:
        return stress_load(args.stress_workers, uuid.uuid4().hex)

    return load


def _live_lock_run(args: Args, run: InheritingRun, rules: SeriesRules) -> Run:
    """`run` with the live lock taken for each run, and the CPU load only while it is held."""
    live_lock = _load_live_lock()
    cache = live_lock.cache_dir()

    def hold() -> AbstractContextManager[int | None]:
        return cast(
            "AbstractContextManager[int | None]", live_lock.hold_live_lock(cache, os.environ)
        )

    return locked_run(run, hold=hold, load=_each_run_load(args), rules=rules)


def _run_keeping(failure_log: Path | None) -> InheritingRun:
    """`run_once`, keeping a failing run's output in `failure_log` (if given)."""

    def run(
        uv: str, pytest_args: Sequence[str], inherit: Sequence[int]
    ) -> tuple[int, frozenset[str]]:
        return run_once(uv, pytest_args, inherit, failure_log=failure_log)

    return run


def _without_lock(run: InheritingRun) -> Run:
    """`run`, inheriting no descriptor."""

    def run_unlocked(uv: str, pytest_args: Sequence[str]) -> tuple[int, frozenset[str]]:
        return run(uv, pytest_args, ())

    return run_unlocked


def main(argv: Sequence[str] | None = None) -> int:
    """Run what `argv` describes (`sys.argv[1:]` if None); return the exit code."""
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
    except RepeatError as exc:
        print(f"repeat.py: {exc}", file=sys.stderr)
        return 2
    if is_live_selection(args.pytest_args) and (refusal := _java_refusal()):
        print(
            f"repeat.py: a live selection needs the Java the Reference runs on: {refusal}\n"
            "run it as `mise exec -- uv run scripts/repeat.py ...` (Java 25)",
            file=sys.stderr,
        )
        return 2
    uv = shutil.which("uv")
    if uv is None:
        print("repeat.py: no `uv` on PATH", file=sys.stderr)
        return 2
    failure_log = args.failure_log if args.stop_at_first_failure else None
    keeping = _run_keeping(failure_log)
    rules = SeriesRules(stop_at_first_failure=args.stop_at_first_failure, deadline=args.deadline)
    series = functools.partial(run_repeats, uv, args.pytest_args, args.times, rules=rules)
    if args.live_lock:
        result = series(run=_live_lock_run(args, keeping, rules))
    elif args.stress:
        token = uuid.uuid4().hex
        with stress_load(args.stress_workers, token):
            result = series(run=_without_lock(keeping))
    else:
        result = series(run=_without_lock(keeping))
    return print_report(result, failure_log=failure_log)


if __name__ == "__main__":
    sys.exit(main())
