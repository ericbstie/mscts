#!/usr/bin/env python3
r"""Commit only after `mise run check` is green: THE way to commit in this repo.

Usage:
    python3 scripts/commit_green.py -- <git commit args...>
    (normally invoked as `mise run commit -- -F /abs/msg.txt [git commit args]`)

Checks a captured copy of the index in a temporary checkout, without unstaged or
untracked files. Runs `mise run check` unless `--check-cmd` overrides it for a test,
captures its combined output to a file, and prints the tail. Git commits the captured
index only after exit 0. A failed check leaves the original index and files unchanged.

Limit: the check runs with `UV_NO_SYNC=1` against the repository's real `.venv`, so a
staged change to pyproject.toml or uv.lock is checked against the old environment.

This exists because piping the check into a commit chain has twice let a red
check through: `mise run check | tail && git commit` commits whenever `tail`
exits 0, which it does whether or not the check itself passed -- the pipe's exit
status is the last command's, not the check's. This tool never launders the
check's exit code through a pipe: it captures the check's own output to a file
and inspects the check's own subprocess return code directly.

The check subprocess's environment has every `GIT_*` variable removed, because
this tool is also meant to run inside `git rebase -x "mise run commit -- ...`,
where `GIT_DIR` and friends point at the *rebasing* repository; a test the check
runs (e.g. one that does its own `git init`/`git commit` in a tmp dir) must not
inherit that and write into the real repository instead (see the incident this
guards against, docs/PROCESS.md's retrospective log, 2026-09-26, lead). The
commit keeps the original repository variables, including `GIT_DIR` under a rebase,
and uses the captured index through `GIT_INDEX_FILE`. The original index lock stays
held throughout, so another Git command cannot change what is staged while it checks.
"""

import argparse
import contextlib
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CHECK_CMD: tuple[str, ...] = ("mise", "run", "check")
DEFAULT_TAIL_LINES = 60
_TREE_OPTIONS = (
    "--all",
    "--include",
    "--only",
    "--interactive",
    "--patch",
    "--pathspec-from-file",
    "--pathspec-file-nul",
)
_VALUE_OPTIONS = (
    "--file",
    "--message",
    "--author",
    "--date",
    "--reedit-message",
    "--reuse-message",
    "--fixup",
    "--squash",
    "--trailer",
    "--template",
    "--cleanup",
    "--inter-hunk-context",
)


class CommitError(Exception):
    """Arguments cannot commit the checked index, or `git` is unavailable."""


@dataclass(frozen=True, slots=True)
class Args:
    """One parsed invocation: the check command to run, and the git commit args."""

    check_cmd: tuple[str, ...]
    git_args: tuple[str, ...]
    tail_lines: int


def split_argv(argv: Sequence[str]) -> tuple[list[str], list[str]]:
    """Split `argv` on the first literal "--" into (this tool's own args, git args).

    Raises:
        CommitError: There is no "--" in `argv`.
    """
    if "--" not in argv:
        msg = "missing the '--' separator before the git commit arguments"
        raise CommitError(msg)
    index = argv.index("--")
    return list(argv[:index]), list(argv[index + 1 :])


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="commit_green.py", description="Run the check; commit only if it passed."
    )
    parser.add_argument(
        "--check-cmd",
        default=None,
        help="override the check command (shell-split); for tests only",
    )
    parser.add_argument(
        "--tail", type=int, default=DEFAULT_TAIL_LINES, dest="tail_lines", help="lines to print"
    )
    return parser


def _refuse_selection(argument: str) -> None:
    msg = f"git commit argument {argument!r} can change the tree; stage the intended files first"
    raise CommitError(msg)


def _required_value(args: Sequence[str], index: int) -> str:
    if index + 1 == len(args):
        msg = f"git commit argument {args[index]!r} requires a value"
        raise CommitError(msg)
    return args[index + 1]


def _long_option_end(args: Sequence[str], index: int) -> int:
    argument = args[index]
    option, equals, value = argument.partition("=")
    if any(name.startswith(option) for name in _TREE_OPTIONS):
        _refuse_selection(argument)
    if any(name.startswith(option) for name in _VALUE_OPTIONS):
        if not equals:
            value = _required_value(args, index)
        # --fixup=reword:<commit> implies --only (git-commit manual, #150).
        if "--fixup".startswith(option) and value.startswith("reword:"):
            _refuse_selection(argument)
        return index + (1 if equals else 2)
    return index + 1


def _short_option_end(args: Sequence[str], index: int) -> int:
    argument = args[index]
    for offset, option in enumerate(argument[1:], start=1):
        if option in "aiop":
            _refuse_selection(argument)
        if option in "FmcCt":
            if offset + 1 < len(argument):
                return index + 1
            _required_value(args, index)
            return index + 2
        if option in "SuU":  # optional values are attached to the option, as in -Skey
            return index + 1
    return index + 1


def _validate_git_args(args: Sequence[str]) -> None:
    """Refuse tree-selection flags and paths, while leaving message/amend options intact."""
    index = 0
    while index < len(args):
        argument = args[index]
        if argument == "--":
            if index + 1 < len(args):
                _refuse_selection(args[index + 1])
            return
        if not argument.startswith("-") or argument == "-":
            _refuse_selection(argument)
        index = (
            _long_option_end(args, index)
            if argument.startswith("--")
            else _short_option_end(args, index)
        )


def parse_args(argv: Sequence[str]) -> Args:
    """Parse `argv` (without the program name) into `Args`.

    Raises:
        CommitError: There is no "--", or nothing follows it.
        SystemExit: The part before "--" does not otherwise parse (argparse prints the
            usage message and exits with code 2).
    """
    own, git_args = split_argv(argv)
    if not git_args:
        msg = "no git commit arguments after '--'"
        raise CommitError(msg)
    _validate_git_args(git_args)
    parsed = _build_parser().parse_args(own)
    check_cmd = (
        DEFAULT_CHECK_CMD if parsed.check_cmd is None else tuple(shlex.split(parsed.check_cmd))
    )
    return Args(check_cmd=check_cmd, git_args=tuple(git_args), tail_lines=parsed.tail_lines)


def strip_git_env(env: Mapping[str, str]) -> dict[str, str]:
    """`env` with every `GIT_*` variable removed.

    Under `git rebase -x`, `GIT_DIR`/`GIT_WORK_TREE`/`GIT_INDEX_FILE` point at the
    repository doing the rebase; a subprocess that runs its own git commands (a test
    suite, say) must not inherit those or it can write into that repository by mistake.
    """
    return {key: value for key, value in env.items() if not key.startswith("GIT_")}


def run_check(
    check_cmd: Sequence[str], out_path: Path, *, env: Mapping[str, str], cwd: Path | None = None
) -> int:
    """Run `check_cmd`, its combined stdout+stderr captured to `out_path`; return its exit code.

    Writes straight to a file, never through a pipe: nothing here can launder the
    check's exit status through another command's.
    """
    with out_path.open("wb") as out:
        result = subprocess.run(  # noqa: S603 - argv is caller-controlled, no shell
            list(check_cmd),
            stdout=out,
            stderr=subprocess.STDOUT,
            env=dict(env),
            cwd=cwd,
            check=False,
        )
    return result.returncode


def _git_output(git: str, args: Sequence[str], *, cwd: Path, env: Mapping[str, str]) -> str:
    result = subprocess.run(  # noqa: S603 - fixed git launcher, no shell
        [git, *args], cwd=cwd, env=dict(env), capture_output=True, text=True, check=False
    )
    if result.returncode:
        msg = f"cannot prepare the index: {result.stderr.strip()}"
        raise CommitError(msg)
    return result.stdout.removesuffix("\n")


@contextlib.contextmanager
def _locked_index(index: Path) -> Iterator[None]:
    """Keep other Git commands from staging while the captured index is checked (#150)."""
    lock = index.with_name(f"{index.name}.lock")
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        msg = (
            f"index is already locked: {lock}\n"
            "Another Git command may be running, or an interrupted `mise run commit` left the "
            f"lock behind. Once no Git command runs in this worktree, remove it with `rm {lock}`."
        )
        raise CommitError(msg) from exc
    try:
        yield
    finally:
        os.close(descriptor)
        lock.unlink(missing_ok=True)


def _checkout_tree(
    git: str, root: Path, destination: Path, tree: str, *, env: Mapping[str, str]
) -> None:
    """Check out the captured tree in its own Git repository without making a commit.

    The clone borrows the checkout's objects through `objects/info/alternates`, written
    here because `clone --shared` skips it from a shallow repository (#326) and the
    captured tree is not in the pack it copies instead.
    """
    _git_output(
        git,
        ("clone", "--shared", "--no-checkout", "--quiet", str(root), str(destination)),
        cwd=root,
        env=env,
    )
    objects = _git_output(
        git, ("rev-parse", "--path-format=absolute", "--git-path", "objects"), cwd=root, env=env
    )
    alternates = destination / ".git" / "objects" / "info" / "alternates"
    alternates.parent.mkdir(parents=True, exist_ok=True)
    alternates.write_text(f"{objects}\n")
    _git_output(git, ("read-tree", tree), cwd=destination, env=env)
    _git_output(git, ("checkout-index", "--all"), cwd=destination, env=env)


def _write_import_guard(directory: Path, venv: Path) -> Path:
    """Exclude the editable source path so an untracked package cannot override the index (#150)."""
    sources: list[str] = []
    for path in venv.glob("lib/python*/site-packages/mscts.pth"):
        sources.extend(
            str((path.parent / line).absolute())
            for line in path.read_text().splitlines()
            if line and not line.startswith(("#", "import ", "import\t"))
        )
    directory.mkdir()
    (directory / "sitecustomize.py").write_text(
        "import sys\n"
        f"_editable = {sources!r}\n"
        "sys.path[:] = [path for path in sys.path if path not in _editable]\n"
    )
    return directory


def _check_environment(
    env: Mapping[str, str], snapshot: Path, *, venv: Path | None, guard: Path | None
) -> dict[str, str]:
    """The check's environment; `guard` is the directory `_write_import_guard` wrote."""
    result = strip_git_env(env)
    result["PYTHONPATH"] = str(snapshot / "src")
    result["UV_PROJECT"] = str(snapshot)
    result["UV_NO_SYNC"] = "1"
    result["MISE_TRUSTED_CONFIG_PATHS"] = str(snapshot)
    if venv is not None:
        if guard is not None:
            result["PYTHONPATH"] = os.pathsep.join((str(guard), result["PYTHONPATH"]))
        result["UV_PROJECT_ENVIRONMENT"] = str(venv)
    return result


def tail_of(text: str, n: int) -> str:
    """The last `n` lines of `text`, joined with newlines (fewer if it is shorter)."""
    lines = text.splitlines()
    return "\n".join(lines[-n:])


def run_git_commit(
    git_args: Sequence[str], *, env: Mapping[str, str], cwd: Path | None = None
) -> int:
    """Run `git commit <git_args>` in `cwd` (the current directory if None); return its exit code.

    `env` is passed through unchanged -- `GIT_*` included -- so this keeps working
    inside `git rebase -x`, where `GIT_DIR` legitimately names the repository this
    commit belongs to.

    Raises:
        CommitError: `git` is not on PATH.
    """
    git = shutil.which("git")
    if git is None:
        msg = "no `git` on PATH"
        raise CommitError(msg)
    result = subprocess.run(  # noqa: S603 - fixed, absolute-path launcher; no shell
        [git, "commit", *git_args], env=dict(env), cwd=cwd, check=False
    )
    return result.returncode


def commit_if_green(
    check_cmd: Sequence[str],
    git_args: Sequence[str],
    *,
    tail_lines: int,
    run_check_fn: Callable[[Sequence[str]], tuple[int, str]],
    run_git_commit_fn: Callable[[Sequence[str]], int],
) -> int:
    """Run the check, print its tail, and commit only if it exited 0.

    `run_check_fn` runs the check and returns `(exit code, its full captured output)`;
    `run_git_commit_fn` runs `git commit`. Both do the actual subprocess work, with
    whatever environment their caller bound in (`main` removes `GIT_*` for the check
    and selects the captured index for the commit; tests inject fakes directly).
    Returns the check's exit code if it failed (without ever calling `run_git_commit_fn`),
    otherwise `git commit`'s exit code.
    """
    code, output = run_check_fn(check_cmd)
    print(tail_of(output, tail_lines))
    if code != 0:
        print(f"commit_green: check failed (exit {code}); not committing", file=sys.stderr)
        return code
    return run_git_commit_fn(git_args)


def _captured_tree(
    git: str, index: Path, temporary: Path, *, cwd: Path, env: Mapping[str, str]
) -> tuple[Path, str]:
    """Copy `index` into `temporary`; return the copy and the tree it records."""
    captured = temporary / "index"
    if index.exists():
        shutil.copyfile(index, captured)
    tree = _git_output(git, ("write-tree",), cwd=cwd, env={**env, "GIT_INDEX_FILE": str(captured)})
    return captured, tree


def _snapshot(git: str, root: Path, temporary: Path, tree: str, *, env: Mapping[str, str]) -> Path:
    """Check out `tree` under `temporary`, with the repository's `.venv` linked in."""
    snapshot = temporary / "tree"
    _checkout_tree(git, root, snapshot, tree, env=strip_git_env(env))
    venv = root / ".venv"
    if venv.is_dir():
        (snapshot / ".venv").symlink_to(venv, target_is_directory=True)
    return snapshot


def _commit_checked_index(args: Args, env: Mapping[str, str], cwd: Path) -> int:
    git = shutil.which("git")
    if git is None:
        msg = "no `git` on PATH"
        raise CommitError(msg)
    root = Path(_git_output(git, ("rev-parse", "--show-toplevel"), cwd=cwd, env=env))
    index = Path(
        _git_output(
            git, ("rev-parse", "--path-format=absolute", "--git-path", "index"), cwd=cwd, env=env
        )
    )
    with _locked_index(index), tempfile.TemporaryDirectory(prefix="mscts-commit-index-") as name:
        temporary = Path(name)
        captured, tree = _captured_tree(git, index, temporary, cwd=cwd, env=env)
        commit_env = {**env, "GIT_INDEX_FILE": str(captured)}
        snapshot = _snapshot(git, root, temporary, tree, env=env)
        venv = root / ".venv" if (root / ".venv").is_dir() else None
        guard = _write_import_guard(temporary / "python", venv) if venv else None
        check_env = _check_environment(env, snapshot, venv=venv, guard=guard)

        def run_check_fn(cmd: Sequence[str]) -> tuple[int, str]:
            out_path = temporary / "check.log"
            code = run_check(cmd, out_path, env=check_env, cwd=snapshot)
            return code, out_path.read_text(errors="replace")

        def run_git_commit_fn(git_args: Sequence[str]) -> int:
            return run_git_commit(git_args, env=commit_env, cwd=cwd)

        return commit_if_green(
            args.check_cmd,
            args.git_args,
            tail_lines=args.tail_lines,
            run_check_fn=run_check_fn,
            run_git_commit_fn=run_git_commit_fn,
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Check and commit the index selected by `argv` (`sys.argv[1:]` if None)."""
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
        return _commit_checked_index(args, dict(os.environ), Path.cwd())
    except (CommitError, OSError) as exc:
        print(f"commit_green: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
