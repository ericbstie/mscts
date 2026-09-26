#!/usr/bin/env python3
r"""Time a mise task (typically a tier) in a throwaway copy of the working tree.

Usage:
    python3 scripts/time_tier.py <mise task> [--times N]

Copies the tracked working tree (plus untracked, non-ignored files -- exactly what
`scripts/mutate.py --batch` copies) into a fresh temp dir, looks up `<mise task>`'s
`run` command(s) in `mise.toml`, and runs them there `--times` times (default 1),
never touching this worktree. Each pytest command in the task gets `--durations=10`
appended, so the report can name the slowest tests.

Uses the same uv/venv setup as `scripts/mutate.py --batch` (its "Known traps" in the
`red-green` skill): `UV_PROJECT_ENVIRONMENT` points `uv run --no-sync` at this
worktree's already-synced `.venv` instead of syncing (or trying to create) one under
the copy, and `PYTHONPATH=<copy>/src` puts the copy's own code -- not the original
checkout's -- ahead of the venv's `mscts.pth` on `sys.path`. `--no-sync` guarantees the
run never writes to the shared `.venv`, which matters here more than in a single
mutation: several `--times` runs, or a parallel worker's own `time_tier.py`, could
otherwise race on syncing it.

For each run, prints: the tier's total wall time, the 10 slowest tests (parsed out of
pytest's own `--durations=10` section), and the 1-minute load average (`os.getloadavg()
[0]`) before and after -- so a timing claim always carries the load the machine was
under, per the Worker contract.
"""

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DURATIONS = 10


class TimeTierError(Exception):
    """Bad arguments, a task the mise.toml does not have, or a missing `.venv`/`git`."""


@dataclass(frozen=True, slots=True)
class Args:
    """One parsed invocation: which mise task to time, and how many times."""

    task: str
    times: int


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="time_tier.py", description="Time a mise task in a throwaway copy of the tree."
    )
    parser.add_argument("task", help="a task name from mise.toml, e.g. test:reference")
    parser.add_argument("--times", type=int, default=1, help="how many times to run (default 1)")
    return parser


def parse_args(argv: Sequence[str]) -> Args:
    """Parse `argv` (without the program name) into `Args`.

    Raises:
        TimeTierError: `--times` is not a positive integer.
        SystemExit: the arguments do not otherwise parse, or `task` is missing
            (argparse prints the usage message and exits with code 2).
    """
    parsed = _build_parser().parse_args(argv)
    if parsed.times < 1:
        msg = "--times must be at least 1"
        raise TimeTierError(msg)
    return Args(task=parsed.task, times=parsed.times)


# -- mise.toml: which command(s) a task runs -----------------------------------------


def task_run_commands(mise_toml: Path, task: str) -> list[str]:
    """The shell command(s) `[tasks."<task>"] run` lists in `mise_toml`, as given.

    Raises:
        TimeTierError: `mise_toml` cannot be read or parsed, `task` is not in it, or its
            `run` field is neither a string nor a list of strings.
    """
    try:
        data = tomllib.loads(mise_toml.read_text())
    except OSError as exc:
        msg = f"cannot read {mise_toml}: {exc}"
        raise TimeTierError(msg) from exc
    except tomllib.TOMLDecodeError as exc:
        msg = f"{mise_toml}: not valid TOML: {exc}"
        raise TimeTierError(msg) from exc
    tasks = data.get("tasks", {})
    if task not in tasks:
        msg = f"{mise_toml} has no task {task!r}"
        raise TimeTierError(msg)
    run = tasks[task].get("run")
    if isinstance(run, str):
        return [run]
    if isinstance(run, list) and run:
        commands = [str(command) for command in run if isinstance(command, str)]
        if len(commands) == len(run):
            return commands
    msg = f"task {task!r}'s 'run' field must be a string or a non-empty list of strings"
    raise TimeTierError(msg)


def prepare_command(command: str, *, durations: int = DEFAULT_DURATIONS) -> list[str]:
    """`command` (as `mise.toml` gives it) turned into the argv actually run in a copy.

    A leading "uv run" becomes "uv run --no-sync" (the mutate.py copy trap: never sync
    the shared `.venv` from inside a throwaway copy). A command that names `pytest`
    gets `--durations=<durations>` appended, so its slowest tests can be reported.
    """
    argv = shlex.split(command)
    if argv[:2] == ["uv", "run"]:
        argv = ["uv", "run", "--no-sync", *argv[2:]]
    if "pytest" in argv:
        argv = [*argv, f"--durations={durations}"]
    return argv


# -- the copy (identical to scripts/mutate.py's make_copy; duplicated, not imported, ---
# -- since scripts/ runs standalone -- see scripts/repeat.py's tagged_pids for the same
# -- precedent) ------------------------------------------------------------------------


def _git_executable() -> str:
    """The absolute path to `git` on PATH.

    Raises:
        TimeTierError: `git` is not on PATH.
    """
    git = shutil.which("git")
    if git is None:
        msg = "no `git` on PATH"
        raise TimeTierError(msg)
    return git


def _tracked_files(repo_root: Path) -> list[Path]:
    """Every tracked or untracked-but-not-ignored file for `repo_root`, relative to it."""
    git = _git_executable()
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    result = subprocess.run(  # noqa: S603 - a fixed, absolute-path launcher; no shell
        [git, "-C", str(repo_root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        check=True,
        env=env,
    )
    return [Path(name.decode()) for name in result.stdout.split(b"\0") if name]


def make_copy(repo_root: Path, dest: Path) -> None:
    """Copy every tracked or untracked-but-not-ignored file's content from `repo_root` into `dest`.

    `dest` must not already exist. Never writes to `repo_root` itself.
    """
    dest.mkdir(parents=True)
    for relative in _tracked_files(repo_root):
        source = repo_root / relative
        if not source.is_file():
            continue
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _venv_path(repo_root: Path) -> Path:
    """`repo_root`'s synced virtualenv (`mise run sync` creates it at `<repo_root>/.venv`).

    Raises:
        TimeTierError: it does not exist yet.
    """
    venv = repo_root / ".venv"
    if not venv.is_dir():
        msg = f"{venv} does not exist; run `mise run sync` first"
        raise TimeTierError(msg)
    return venv


def run_in_copy(
    venv: Path, copy_root: Path, argv: Sequence[str]
) -> subprocess.CompletedProcess[str]:
    """Run `argv` inside `copy_root`, using `venv` as is (never syncing it).

    Same environment as `mutate.py`'s `run_pytest_in_copy`: `UV_PROJECT_ENVIRONMENT`
    points at the already-synced `venv`; `PYTHONPATH` puts `copy_root/src` ahead of
    `venv`'s own `mscts.pth` (which names the *original* checkout); `PYTHONDONTWRITEBYTECODE`
    avoids a stale cached bytecode from a same-second copy.
    """
    env = dict(os.environ)
    env["UV_PROJECT_ENVIRONMENT"] = str(venv)
    env["PYTHONPATH"] = str(copy_root / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(  # noqa: S603 - a fixed, absolute-path launcher; no shell
        argv, cwd=copy_root, env=env, capture_output=True, text=True, check=False
    )


# -- parsing pytest's own --durations output -----------------------------------------

_DURATIONS_HEADER_RE = re.compile(r"slowest \d+ durations", re.IGNORECASE)
_DURATIONS_LINE_RE = re.compile(r"^\d+\.\d+s\s+\S+\s+\S+")


def parse_slowest_durations(pytest_output: str) -> list[str]:
    """The lines of pytest's own "slowest N durations" section in `pytest_output`.

    Returns each entry line verbatim (stripped), e.g. "20.01s call
    tests/reference/test_join_reference.py::test_...". Returns `[]` if the section is
    not there (e.g. `--durations` was not passed, or nothing took measurable time).
    """
    lines = pytest_output.splitlines()
    for index, line in enumerate(lines):
        if not _DURATIONS_HEADER_RE.search(line):
            continue
        collected: list[str] = []
        for later in lines[index + 1 :]:
            stripped = later.strip()
            if _DURATIONS_LINE_RE.match(stripped):
                collected.append(stripped)
            elif not stripped:
                continue
            else:
                break
        return collected
    return []


# -- running the tier once, in its own throwaway copy --------------------------------


@dataclass(frozen=True, slots=True)
class RunResult:
    """One run's timing.

    Total wall time, the 1-minute load average before/after, and the slowest-duration
    lines pytest reported.
    """

    total_s: float
    load_before: float
    load_after: float
    slowest: list[str]


@dataclass(frozen=True, slots=True)
class CopyHooks:
    """`run_tier_once`'s replaceable parts: the copy, the load reader, and its tempdir.

    Real use keeps every default (the real `make_copy`, `os.getloadavg`, and a fresh
    `tempfile.mkdtemp`); tests override one or more to stay hermetic and inspectable.
    """

    make_copy: Callable[[Path, Path], None] = make_copy
    get_load: Callable[[], float] = lambda: os.getloadavg()[0]
    new_copy_root: Callable[[], Path] | None = None


def _new_copy_root(hooks: CopyHooks) -> Path:
    if hooks.new_copy_root is not None:
        return hooks.new_copy_root()
    return Path(tempfile.mkdtemp(prefix="mscts-time-tier-")) / "copy"


def run_tier_once(
    repo_root: Path,
    task_commands: Sequence[str],
    run: Callable[[Path, Sequence[str]], subprocess.CompletedProcess[str]],
    *,
    durations: int = DEFAULT_DURATIONS,
    hooks: CopyHooks | None = None,
) -> RunResult:
    """Copy `repo_root`, run each of `task_commands` there once, and report the timing.

    `run(copy_root, argv)` executes one prepared command inside the copy (real use
    passes a `uv`/venv-aware subprocess call; tests inject a fake, so the aggregation
    is pinned without spawning real pytest). The copy is always removed, even if a
    command raises. `hooks`, when given, replaces one or more of the real copy/load/
    tempdir calls (see `CopyHooks`).
    """
    hooks = hooks or CopyHooks()
    copy_root = _new_copy_root(hooks)
    try:
        hooks.make_copy(repo_root, copy_root)
        load_before = hooks.get_load()
        start = time.perf_counter()
        outputs: list[str] = []
        for command in task_commands:
            argv = prepare_command(command, durations=durations)
            result = run(copy_root, argv)
            outputs.append(result.stdout + result.stderr)
        total_s = time.perf_counter() - start
        load_after = hooks.get_load()
    finally:
        shutil.rmtree(copy_root.parent, ignore_errors=True)
    slowest: list[str] = []
    for output in outputs:
        slowest.extend(parse_slowest_durations(output))
    return RunResult(
        total_s=total_s, load_before=load_before, load_after=load_after, slowest=slowest
    )


def print_run_report(index: int, times: int, result: RunResult) -> None:
    """Print one run's report: header line, then its slowest durations, if any."""
    print(
        f"run {index}/{times}: tier total {result.total_s:.1f}s, "
        f"load avg before {result.load_before:.2f}, after {result.load_after:.2f}"
    )
    if result.slowest:
        print(f"  slowest {len(result.slowest)} durations:")
        for line in result.slowest:
            print(f"    {line}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run what `argv` describes (`sys.argv[1:]` if None); return the exit code."""
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
    except TimeTierError as exc:
        print(f"time_tier.py: {exc}", file=sys.stderr)
        return 2
    repo_root = Path(__file__).resolve().parent.parent
    try:
        task_commands = task_run_commands(repo_root / "mise.toml", args.task)
        venv = _venv_path(repo_root)
    except TimeTierError as exc:
        print(f"time_tier.py: {exc}", file=sys.stderr)
        return 2

    def run(copy_root: Path, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return run_in_copy(venv, copy_root, command)

    for index in range(1, args.times + 1):
        try:
            result = run_tier_once(repo_root, task_commands, run)
        except TimeTierError as exc:
            print(f"time_tier.py: {exc}", file=sys.stderr)
            return 2
        print_run_report(index, args.times, result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
