#!/usr/bin/env python3
"""Mutation runner: prove a test bites by mutating the code it covers and watching it fail.

Usage (one mutation):
    python3 scripts/mutate.py [--timeout SECONDS] [--skip-baseline] <file> <old> <new>
        -- <pytest args...>

Backs up `<file>`, checks that `<old>` occurs in it exactly once, replaces that one
occurrence with `<new>`, runs `uv run pytest <pytest args...>` under a timeout (default
60 s), and always restores `<file>` from the backup: on a normal return, a test
failure, a timeout, or Ctrl-C.

Usage (batch mode):
    python3 scripts/mutate.py --batch <spec.json> [--jobs N] -- <pytest args...>

`<spec.json>` is a JSON list of `{"file": ..., "old": ..., "new": ..., "id": ...}`
objects (`id` defaults to the entry's 1-based position). Each mutation runs in its own
throwaway copy of the tracked working tree, so mutations never collide and the original
worktree is never modified; `--jobs N` runs up to N of them at once (default 1).

The verdict is KILLED only when pytest actually ran the selection and at least one test
FAILED (exit code 1): that is the only outcome that proves the tests bite. A timeout, or
any other pytest exit code -- 2 (interrupted), 3 (internal error), 4 (usage error, e.g. a
mistyped path) or 5 (no tests collected) -- is INVALID: pytest did not cleanly pass or
fail the selection, so neither KILLED nor SURVIVED can be trusted from it (see MD6,
docs/audits/2026-09-26-foundation.md). Before mutating, both modes first run the same
pytest selection unmutated (once per mutation, or once for the whole batch): a mutation
can only be judged against a green baseline. `--skip-baseline` skips that check.

Exit code:
    0   KILLED: pytest ran the selection and at least one test failed (batch mode: every
        mutation was KILLED).
    1   SURVIVED: pytest ran the selection and every test passed (batch mode: at least
        one mutation SURVIVED or was INVALID).
    2   the arguments were bad, the batch spec was malformed, `<old>` did not occur in
        `<file>` exactly once, or `uv` (or, in batch mode, a synced `.venv`) was missing.
    3   INVALID: the pytest run proves neither KILLED nor SURVIVED (see above).
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    """One parsed single-mutation invocation: the mutation, and the pytest run to check it with."""

    file: Path
    old: str
    new: str
    pytest_args: tuple[str, ...]
    timeout_s: float
    skip_baseline: bool


@dataclass(frozen=True, slots=True)
class BatchArgs:
    """One parsed `--batch` invocation: the spec file, and the pytest run to check it with."""

    spec: Path
    pytest_args: tuple[str, ...]
    timeout_s: float
    jobs: int
    skip_baseline: bool


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
    parser.add_argument("file", type=Path, nargs="?")
    parser.add_argument("old", nargs="?")
    parser.add_argument("new", nargs="?")
    parser.add_argument(
        "--batch",
        type=Path,
        default=None,
        help="a JSON spec of mutations; see the module docstring",
    )
    parser.add_argument(
        "--jobs", type=int, default=1, help="--batch only: how many mutations to run at once"
    )
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S, dest="timeout_s")
    parser.add_argument(
        "--skip-baseline",
        action="store_true",
        dest="skip_baseline",
        help="skip the no-op sanity run (the caller already knows the selection is green)",
    )
    return parser


def parse_args(argv: Sequence[str]) -> Args | BatchArgs:
    """Parse `argv` (without the program name) into `Args` or, with `--batch`, `BatchArgs`.

    Raises:
        MutateError: There is no "--", or nothing follows it; `--batch` is combined with
            `<file> <old> <new>`; `<file> <old> <new>` are not all given without
            `--batch`; or `--jobs` is not a positive integer, or is given without
            `--batch`.
        SystemExit: The part before "--" does not otherwise parse (argparse prints the
            usage message and exits with code 2).
    """
    own, pytest_args = split_argv(argv)
    if not pytest_args:
        msg = "no pytest arguments after '--'"
        raise MutateError(msg)
    parsed = _build_parser().parse_args(own)
    if parsed.batch is not None:
        return _batch_args(parsed, pytest_args)
    return _single_args(parsed, pytest_args)


def _batch_args(parsed: argparse.Namespace, pytest_args: list[str]) -> BatchArgs:
    if parsed.file is not None or parsed.old is not None or parsed.new is not None:
        msg = "--batch cannot be combined with <file> <old> <new>"
        raise MutateError(msg)
    if parsed.jobs < 1:
        msg = "--jobs must be at least 1"
        raise MutateError(msg)
    return BatchArgs(
        spec=parsed.batch,
        pytest_args=tuple(pytest_args),
        timeout_s=parsed.timeout_s,
        jobs=parsed.jobs,
        skip_baseline=parsed.skip_baseline,
    )


def _single_args(parsed: argparse.Namespace, pytest_args: list[str]) -> Args:
    if parsed.file is None or parsed.old is None or parsed.new is None:
        msg = "file, old and new are required unless --batch is given"
        raise MutateError(msg)
    if parsed.jobs != 1:
        msg = "--jobs only applies with --batch"
        raise MutateError(msg)
    return Args(
        file=parsed.file,
        old=parsed.old,
        new=parsed.new,
        pytest_args=tuple(pytest_args),
        timeout_s=parsed.timeout_s,
        skip_baseline=parsed.skip_baseline,
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


def sha256_of(data: bytes) -> str:
    """The hex sha256 digest of `data`."""
    return hashlib.sha256(data).hexdigest()


def restore(file: Path, backup: Path) -> None:
    """Put `backup`'s content back at `file`, verify it by sha256, and remove `backup`.

    Raises:
        MutateError: the bytes written to `file` do not sha256-match `backup` (the write
            silently failed, or something else changed `file` in between). `backup` is
            kept, deliberately, so the mismatch can be inspected; nothing is unlinked.
    """
    original = backup.read_bytes()
    file.write_bytes(original)
    restored = file.read_bytes()
    if sha256_of(restored) != sha256_of(original):
        msg = (
            f"{file}: restored content does not match {backup} by sha256; "
            "the backup was kept -- restore it by hand before trusting this file again"
        )
        raise MutateError(msg)
    backup.unlink()


def run_pytest(uv: str, pytest_args: Sequence[str], *, timeout_s: float) -> int | None:
    """Run `uv run pytest <pytest_args>`; return its exit code, or None if it timed out.

    `PYTHONDONTWRITEBYTECODE=1` stops pytest from writing a `.pyc` for the mutated file:
    without it, a same-size, same-second restore can leave a stale cached bytecode behind
    that a later, unmutated run then imports instead of the restored source.
    """
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        result = subprocess.run(  # noqa: S603 - a fixed, absolute-path launcher; no shell
            [uv, "run", "pytest", *pytest_args], env=env, timeout=timeout_s, check=False
        )
    except subprocess.TimeoutExpired:
        return None
    return result.returncode


# -- batch mode: many mutations, each in its own throwaway copy of the repository -------


@dataclass(frozen=True, slots=True)
class MutationSpec:
    """One batch-mode mutation: `old` -> `new` in `file` (repo-relative), named `id`."""

    id: str
    file: str
    old: str
    new: str


def _parse_batch_entry(path: Path, index: int, entry: object, seen_ids: set[str]) -> MutationSpec:
    """Validate and convert `raw[index]` (from `parse_batch_spec`) into a `MutationSpec`."""
    if not isinstance(entry, dict):
        msg = f"{path}[{index}]: expected an object, got {type(entry).__name__}"
        raise MutateError(msg)
    fields: dict[str, object] = {key: value for key, value in entry.items() if isinstance(key, str)}
    file_value = fields.get("file")
    old_value = fields.get("old")
    new_value = fields.get("new")
    if (
        not isinstance(file_value, str)
        or not isinstance(old_value, str)
        or not isinstance(new_value, str)
    ):
        msg = f"{path}[{index}]: 'file', 'old' and 'new' must all be strings"
        raise MutateError(msg)
    mutation_id = fields.get("id", str(index + 1))
    if not isinstance(mutation_id, str):
        msg = f"{path}[{index}]: 'id' must be a string"
        raise MutateError(msg)
    if mutation_id in seen_ids:
        msg = f"{path}: duplicate mutation id {mutation_id!r}"
        raise MutateError(msg)
    seen_ids.add(mutation_id)
    return MutationSpec(id=mutation_id, file=file_value, old=old_value, new=new_value)


def parse_batch_spec(path: Path) -> list[MutationSpec]:
    """Load and validate `path`: a JSON list of `{file, old, new, [id]}` mutations.

    A missing `id` defaults to the entry's 1-based position, as a string.

    Raises:
        MutateError: `path` cannot be read, is not valid JSON, is not a non-empty list,
            an entry is not an object with string `file`/`old`/`new` (and a string `id`
            if given), or two entries share an id.
    """
    try:
        raw_text = path.read_text()
    except OSError as exc:
        msg = f"cannot read batch spec {path}: {exc}"
        raise MutateError(msg) from exc
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        msg = f"{path}: not valid JSON: {exc}"
        raise MutateError(msg) from exc
    if not isinstance(raw, list) or not raw:
        msg = f"{path}: expected a non-empty JSON list of mutations"
        raise MutateError(msg)
    seen_ids: set[str] = set()
    return [_parse_batch_entry(path, index, entry, seen_ids) for index, entry in enumerate(raw)]


def _git_executable() -> str:
    """The absolute path to `git` on PATH.

    Raises:
        MutateError: `git` is not on PATH.
    """
    git = shutil.which("git")
    if git is None:
        msg = "no `git` on PATH"
        raise MutateError(msg)
    return git


def _tracked_files(repo_root: Path) -> list[Path]:
    """Every file `git ls-files` reports for `repo_root`, as paths relative to it."""
    git = _git_executable()
    # Drop GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE, ...: under `git rebase -x` they point at
    # whichever repository runs the rebase, and would override `-C repo_root`.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    result = subprocess.run(  # noqa: S603 - a fixed, absolute-path launcher; no shell
        [git, "-C", str(repo_root), "ls-files", "-z"], capture_output=True, check=True, env=env
    )
    return [Path(name.decode()) for name in result.stdout.split(b"\0") if name]


def make_copy(repo_root: Path, dest: Path) -> None:
    """Copy every tracked file's current content from `repo_root` into `dest`.

    Content is read from the working tree, not git's index, so this reflects uncommitted
    edits; a file that is tracked but was deleted in the working tree is skipped, and a
    file that was never `git add`ed is not copied at all (a documented limitation, not a
    concern for a worker's own green worktree). `dest` must not already exist. Never
    writes to `repo_root` itself.
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
        MutateError: it does not exist yet.
    """
    venv = repo_root / ".venv"
    if not venv.is_dir():
        msg = f"{venv} does not exist; run `mise run sync` first"
        raise MutateError(msg)
    return venv


def run_pytest_in_copy(
    uv: str, venv: Path, copy_root: Path, pytest_args: Sequence[str], *, timeout_s: float
) -> int | None:
    """Run `uv run --no-sync pytest <pytest_args>` inside `copy_root`, using `venv` as is.

    `UV_PROJECT_ENVIRONMENT` points uv at the already-synced `venv` instead of creating
    one relative to `copy_root` (which has no `.venv` of its own, so plain `uv run` would
    try to resolve and build a brand new one there); `--no-sync` then stops uv from
    checking or writing to `venv` at all -- verified live: `venv`'s own files are
    byte-for-byte unchanged after a run. `PYTHONPATH` puts `copy_root/src` ahead of
    `venv`'s own `mscts.pth` (which still names the *original* checkout's `src/`), so the
    copy's own code -- mutated or not -- is what is actually imported and tested; without
    it, every mutation would silently test the unmutated original and always SURVIVE.
    `PYTHONDONTWRITEBYTECODE=1` as in `run_pytest`.
    """
    env = dict(os.environ)
    env["UV_PROJECT_ENVIRONMENT"] = str(venv)
    env["PYTHONPATH"] = str(copy_root / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        result = subprocess.run(  # noqa: S603 - fixed launcher, absolute cwd, no shell
            [uv, "run", "--no-sync", "pytest", *pytest_args],
            cwd=copy_root,
            env=env,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None
    return result.returncode


@dataclass(frozen=True, slots=True)
class MutationResult:
    """One batch mutation's id and `Outcome`."""

    id: str
    outcome: Outcome


@dataclass(frozen=True, slots=True)
class BatchOptions:
    """The pytest run shared by every mutation in a batch."""

    pytest_args: tuple[str, ...]
    timeout_s: float
    jobs: int
    skip_baseline: bool


def run_one_batch_mutation(
    repo_root: Path,
    spec: MutationSpec,
    options: BatchOptions,
    *,
    make_copy: Callable[[Path, Path], None],
    run_in_copy: Callable[[Path, Sequence[str], float], int | None],
) -> MutationResult:
    """Copy `repo_root`, apply `spec`'s mutation in the copy, run it, and report its Outcome.

    The copy is always removed before returning. `spec.file` not existing as a file in
    the copy, or `spec.old` not occurring in it exactly once, is reported as INVALID
    (never as a crash), so one bad entry cannot take down the rest of a batch.
    """
    # mkdtemp's own directory is the throwaway parent to remove afterwards; `copy_root`
    # itself must not exist yet, per `make_copy`'s contract.
    copy_root = Path(tempfile.mkdtemp(prefix="mscts-mutate-")) / "copy"
    try:
        make_copy(repo_root, copy_root)
        target = copy_root / spec.file
        if not target.is_file():
            return MutationResult(
                spec.id, Outcome("INVALID", f"{spec.file}: not a file in the tracked tree")
            )
        text = target.read_text()
        try:
            check_single_occurrence(text, spec.old)
        except MutateError as exc:
            return MutationResult(spec.id, Outcome("INVALID", str(exc)))
        target.write_text(mutate_text(text, spec.old, spec.new))
        returncode = run_in_copy(copy_root, options.pytest_args, options.timeout_s)
        return MutationResult(spec.id, classify(returncode))
    finally:
        shutil.rmtree(copy_root.parent, ignore_errors=True)


def run_batch(
    repo_root: Path,
    specs: Sequence[MutationSpec],
    options: BatchOptions,
    *,
    make_copy: Callable[[Path, Path], None],
    run_in_copy: Callable[[Path, Sequence[str], float], int | None],
) -> Outcome | list[MutationResult]:
    """Run every mutation in `specs`, each in its own throwaway copy; return their results.

    Unless `options.skip_baseline`, first runs `options.pytest_args` against one
    unmutated copy: a mutation can only be judged against a green baseline. If that is
    not green, returns a single INVALID `Outcome` for the whole batch, and runs no
    mutations at all. Otherwise runs every mutation (up to `options.jobs` at once) and
    returns one `MutationResult` per spec, in `specs`' order.
    """
    if not options.skip_baseline:
        # As in run_one_batch_mutation: mkdtemp's own directory is the throwaway parent
        # to remove afterwards; baseline_root itself must not exist yet.
        baseline_root = Path(tempfile.mkdtemp(prefix="mscts-mutate-baseline-")) / "copy"
        try:
            make_copy(repo_root, baseline_root)
            baseline_returncode = run_in_copy(baseline_root, options.pytest_args, options.timeout_s)
        finally:
            shutil.rmtree(baseline_root.parent, ignore_errors=True)
        if baseline_returncode != 0:
            detail = (
                "the selection is not green before mutating "
                f"(pytest exit code {_format_exit(baseline_returncode)})"
            )
            return Outcome("INVALID", detail)
    with ThreadPoolExecutor(max_workers=options.jobs) as pool:
        futures = {
            pool.submit(
                run_one_batch_mutation,
                repo_root,
                spec,
                options,
                make_copy=make_copy,
                run_in_copy=run_in_copy,
            ): spec.id
            for spec in specs
        }
        by_id = {futures[future]: future.result() for future in as_completed(futures)}
    return [by_id[spec.id] for spec in specs]


_EXIT_BY_KIND: dict[str, int] = {"KILLED": 0, "SURVIVED": 1, "INVALID": 3}
_EXIT_BAD_ARGS = 2


@dataclass(frozen=True, slots=True)
class Mutation:
    """One `old` -> `new` replacement to try in `file`."""

    file: Path
    old: str
    new: str


def _format_exit(returncode: int | None) -> str:
    """`returncode` for a message: "timeout" if it is None, else the number."""
    return "timeout" if returncode is None else str(returncode)


def run_mutation(
    mutation: Mutation,
    pytest_args: Sequence[str],
    *,
    timeout_s: float,
    run: Callable[[Sequence[str], float], int | None],
    skip_baseline: bool = False,
) -> Outcome:
    """Apply `mutation`, run it, always restore, and classify the result.

    `run(pytest_args, timeout_s)` executes the pytest selection and returns its exit code
    (None on a timeout). Real use passes a `uv run pytest` subprocess call; tests inject a
    fake, so every exit code `classify` distinguishes is pinned without spawning pytest.

    Unless `skip_baseline`, first runs `pytest_args` against `mutation.file` as it stands:
    a mutation can only be judged against a green baseline. If that run does not pass
    (exit code 0), returns INVALID ("the selection is not green before mutating") without
    ever touching `mutation.file`. Pass `skip_baseline=True` only when the baseline was
    already checked once elsewhere for this exact selection (batch mode does, over the
    whole batch, rather than once per mutation).

    Raises:
        MutateError: `mutation.old` does not occur in `mutation.file` exactly once, or a
            backup from a previous, uncleaned run already exists. Neither case runs `run`
            or touches `mutation.file`.
    """
    if not skip_baseline:
        baseline_returncode = run(pytest_args, timeout_s)
        if baseline_returncode != 0:
            detail = (
                "the selection is not green before mutating "
                f"(pytest exit code {_format_exit(baseline_returncode)})"
            )
            return Outcome("INVALID", detail)
    backup = backup_path(mutation.file)
    apply_mutation(mutation.file, backup, mutation.old, mutation.new)
    try:
        returncode = run(pytest_args, timeout_s)
    finally:
        restore(mutation.file, backup)
    return classify(returncode)


def _run_single(args: Args) -> int:
    """The single-mutation `main()` path: apply `args`'s mutation and print its Outcome."""
    uv = shutil.which("uv")
    if uv is None:
        print("mutate.py: no `uv` on PATH", file=sys.stderr)
        return _EXIT_BAD_ARGS

    def run(pytest_args: Sequence[str], timeout_s: float) -> int | None:
        return run_pytest(uv, pytest_args, timeout_s=timeout_s)

    mutation = Mutation(args.file, args.old, args.new)
    try:
        outcome = run_mutation(
            mutation,
            args.pytest_args,
            timeout_s=args.timeout_s,
            run=run,
            skip_baseline=args.skip_baseline,
        )
    except MutateError as exc:
        print(f"mutate.py: {exc}", file=sys.stderr)
        return _EXIT_BAD_ARGS
    print(f"{outcome.kind}: {outcome.detail}")
    return _EXIT_BY_KIND[outcome.kind]


def print_batch_report(results: list[MutationResult]) -> int:
    """Print one line per result and a summary; return the exit code (1 if any did not KILL)."""
    counts = Counter(result.outcome.kind for result in results)
    for result in results:
        print(f"{result.id} {result.outcome.kind}: {result.outcome.detail}")
    summary = ", ".join(
        f"{counts[kind]} {kind}" for kind in ("KILLED", "SURVIVED", "INVALID") if counts[kind]
    )
    print(f"{len(results)} mutation(s): {summary}")
    if counts["SURVIVED"] or counts["INVALID"]:
        return _EXIT_BY_KIND["SURVIVED"]
    return _EXIT_BY_KIND["KILLED"]


def _run_batch(args: BatchArgs) -> int:
    """The `--batch` `main()` path: run every mutation in `args.spec` and print a report."""
    try:
        specs = parse_batch_spec(args.spec)
    except MutateError as exc:
        print(f"mutate.py: {exc}", file=sys.stderr)
        return _EXIT_BAD_ARGS
    uv = shutil.which("uv")
    if uv is None:
        print("mutate.py: no `uv` on PATH", file=sys.stderr)
        return _EXIT_BAD_ARGS
    repo_root = Path(__file__).resolve().parent.parent
    try:
        venv = _venv_path(repo_root)
    except MutateError as exc:
        print(f"mutate.py: {exc}", file=sys.stderr)
        return _EXIT_BAD_ARGS

    def run_in_copy(copy_root: Path, pytest_args: Sequence[str], timeout_s: float) -> int | None:
        return run_pytest_in_copy(uv, venv, copy_root, pytest_args, timeout_s=timeout_s)

    options = BatchOptions(
        pytest_args=args.pytest_args,
        timeout_s=args.timeout_s,
        jobs=args.jobs,
        skip_baseline=args.skip_baseline,
    )
    try:
        outcome_or_results = run_batch(
            repo_root, specs, options, make_copy=make_copy, run_in_copy=run_in_copy
        )
    except MutateError as exc:
        # A per-mutation copy can fail for a reason `run_one_batch_mutation` does not
        # turn into an INVALID Outcome (e.g. `git` vanishing from PATH mid-run); report it
        # like any other setup error instead of letting a bare traceback end the batch.
        print(f"mutate.py: {exc}", file=sys.stderr)
        return _EXIT_BAD_ARGS
    if isinstance(outcome_or_results, Outcome):
        print(f"{outcome_or_results.kind}: {outcome_or_results.detail}")
        return _EXIT_BY_KIND[outcome_or_results.kind]
    return print_batch_report(outcome_or_results)


def main(argv: Sequence[str] | None = None) -> int:
    """Run what `argv` describes (`sys.argv[1:]` if None): one mutation, or a `--batch`."""
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
    except MutateError as exc:
        print(f"mutate.py: {exc}", file=sys.stderr)
        return _EXIT_BAD_ARGS
    if isinstance(args, BatchArgs):
        return _run_batch(args)
    return _run_single(args)


if __name__ == "__main__":
    sys.exit(main())
