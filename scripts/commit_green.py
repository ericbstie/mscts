#!/usr/bin/env python3
r"""Commit only after `mise run check` is green: THE way to commit in this repo.

Usage:
    python3 scripts/commit_green.py -- <git commit args...>
    (normally invoked as `mise run commit -- -F /abs/msg.txt [git commit args]`)

Runs the check command (`mise run check` unless `--check-cmd` overrides it for a
test), with its combined stdout+stderr captured straight to a temp file -- never
through a pipe -- then prints that file's tail. `git commit <args>` runs only if
the check exited 0; otherwise this prints the tail (the failing part) and exits
with the check's own exit code, without ever calling `git commit`.

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
`git commit` subprocess keeps the ambient environment, `GIT_*` included, exactly
as inherited: under `git rebase -x`, that is what makes the commit land in the
repository the rebase is actually rewriting, which is the legitimate use of
`GIT_DIR` this tool must not break.
"""

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CHECK_CMD: tuple[str, ...] = ("mise", "run", "check")
DEFAULT_TAIL_LINES = 60


class CommitError(Exception):
    """Bad arguments: no '--' separator, nothing after it, or no `git` on PATH."""


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


def run_check(check_cmd: Sequence[str], out_path: Path, *, env: Mapping[str, str]) -> int:
    """Run `check_cmd`, its combined stdout+stderr captured to `out_path`; return its exit code.

    Writes straight to a file, never through a pipe: nothing here can launder the
    check's exit status through another command's.
    """
    with out_path.open("wb") as out:
        result = subprocess.run(  # noqa: S603 - argv is caller-controlled, no shell
            list(check_cmd), stdout=out, stderr=subprocess.STDOUT, env=dict(env), check=False
        )
    return result.returncode


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
    whatever environment their caller bound in (`main` gives the check a `GIT_*`-stripped
    environment and the commit the ambient one unchanged; tests inject fakes directly).
    Returns the check's exit code if it failed (without ever calling `run_git_commit_fn`),
    otherwise `git commit`'s exit code.
    """
    code, output = run_check_fn(check_cmd)
    print(tail_of(output, tail_lines))
    if code != 0:
        print(f"commit_green: check failed (exit {code}); not committing", file=sys.stderr)
        return code
    return run_git_commit_fn(git_args)


def main(argv: Sequence[str] | None = None) -> int:
    """Run what `argv` describes (`sys.argv[1:]` if None): the check, then maybe the commit."""
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
    except CommitError as exc:
        print(f"commit_green: {exc}", file=sys.stderr)
        return 2

    check_env = strip_git_env(os.environ)
    commit_env = dict(os.environ)

    def run_check_fn(cmd: Sequence[str]) -> tuple[int, str]:
        fd, name = tempfile.mkstemp(prefix="mscts-commit-check-", suffix=".log")
        os.close(fd)
        out_path = Path(name)
        try:
            code = run_check(cmd, out_path, env=check_env)
            return code, out_path.read_text(errors="replace")
        finally:
            out_path.unlink(missing_ok=True)

    def run_git_commit_fn(git_args: Sequence[str]) -> int:
        try:
            return run_git_commit(git_args, env=commit_env)
        except CommitError as exc:
            print(f"commit_green: {exc}", file=sys.stderr)
            return 2

    return commit_if_green(
        args.check_cmd,
        args.git_args,
        tail_lines=args.tail_lines,
        run_check_fn=run_check_fn,
        run_git_commit_fn=run_git_commit_fn,
    )


if __name__ == "__main__":
    sys.exit(main())
