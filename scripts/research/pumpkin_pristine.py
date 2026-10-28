#!/usr/bin/env python3
"""Research only: what a Pumpkin build writes on its first run, against the committed copy.

Usage:
    uv run scripts/research/pumpkin_pristine.py BINARY [--committed FILE] [--timeout S]

Run it after a nightly bump (src/mscts/adapters/pumpkin/SOURCE.md). It starts BINARY once
in an empty temporary directory with an empty environment (`PATH` only), inside a new
network namespace (`unshare -rn`) when the host allows one, so Pumpkin's pristine defaults
(`0.0.0.0:25565`, telemetry, Bedrock) reach nothing. It waits for `pumpkin.toml` to appear
and parse, or for the process to exit, for at most `--timeout` seconds (default 30), stops
the process, and prints a unified diff of the file against `--committed` (default: the
Adapter's `pumpkin.toml`), ignoring the top-level `seed`, which is random on every first run.

Exit code 0: no difference. 1: the diff is printed. 2: BINARY wrote no `pumpkin.toml`; its
last output goes to stderr.
"""

import argparse
import contextlib
import difflib
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO

REPO = Path(__file__).resolve().parents[2]
COMMITTED = REPO / "src" / "mscts" / "adapters" / "pumpkin" / "pumpkin.toml"
CONFIG_NAME = "pumpkin.toml"
DEFAULT_TIMEOUT = 30.0
POLL_INTERVAL = 0.1
STOP_GRACE = 5.0
OUTPUT_TAIL_BYTES = 3000
_SEED_LINE = re.compile(r"seed\s*=")


@dataclass(frozen=True)
class Pristine:
    """What one first run left behind: the config it wrote (None if none) and its last output."""

    config: str | None
    output: str


def unshare_works() -> bool:
    """True if this host lets us start a command in a new network namespace (`unshare -rn`)."""
    if shutil.which("unshare") is None:
        return False
    try:
        probe = subprocess.run(
            ["unshare", "-rn", "true"],  # noqa: S607
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


def pristine_command(binary: Path, *, use_unshare: bool) -> list[str]:
    """The argv that starts `binary`, inside a new network namespace if `use_unshare`."""
    return ["unshare", "-rn", str(binary)] if use_unshare else [str(binary)]


def _written_config(workdir: Path) -> str | None:
    """The `pumpkin.toml` in `workdir` once it is there and written, else None.

    A file that is still empty (created, not yet written) or does not parse is not written.
    """
    try:
        text = (workdir / CONFIG_NAME).read_text()
        tomllib.loads(text)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    return text if text.strip() else None


def _wait_for_config(proc: subprocess.Popen[bytes], workdir: Path, timeout: float) -> str | None:
    """The config `proc` writes into `workdir`, or None if it exits or `timeout` passes first."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        config = _written_config(workdir)
        if config is not None:
            return config
        if proc.poll() is not None:
            return _written_config(workdir)
        time.sleep(POLL_INTERVAL)
    return None


def _stop(proc: subprocess.Popen[bytes]) -> None:
    """Stop `proc` and what it started if it still runs: SIGTERM its process group, then SIGKILL.

    A `proc` that has exited and been reaped is left alone: its pid may name another group now.
    """
    for signum in (signal.SIGTERM, signal.SIGKILL):
        if proc.poll() is not None:
            return
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signum)
        try:
            proc.wait(timeout=STOP_GRACE)
        except subprocess.TimeoutExpired:
            continue
        return


def _tail(output: IO[bytes], size: int) -> str:
    """The last `size` bytes of the open file `output`, as text."""
    output.seek(0, os.SEEK_END)
    output.seek(max(0, output.tell() - size))
    return output.read().decode(errors="replace")


def run_pristine(
    binary: Path, workdir: Path, *, use_unshare: bool, timeout: float, path: str
) -> Pristine:
    """Run `binary` once in the empty `workdir`, its environment `PATH=path` only; stop it."""
    with tempfile.TemporaryFile() as output:
        proc = subprocess.Popen(  # noqa: S603
            pristine_command(binary, use_unshare=use_unshare),
            cwd=workdir,
            env={"PATH": path},
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            config = _wait_for_config(proc, workdir, timeout)
        finally:
            _stop(proc)
        return Pristine(config=config, output=_tail(output, OUTPUT_TAIL_BYTES))


def _without_seed(text: str) -> list[str]:
    """`text`'s lines but for the top-level `seed` (a `seed` inside a table stays)."""
    kept: list[str] = []
    in_table = False
    for line in text.splitlines():
        in_table = in_table or line.startswith("[")
        if in_table or not _SEED_LINE.match(line):
            kept.append(line)
    return kept


def config_diff(committed: str, fresh: str, *, fresh_name: str) -> str:
    """A unified diff from `committed` to `fresh`, ignoring the top-level `seed`; "" if none."""
    lines = difflib.unified_diff(
        _without_seed(committed),
        _without_seed(fresh),
        fromfile=f"{CONFIG_NAME} (committed)",
        tofile=f"{CONFIG_NAME} ({fresh_name})",
        lineterm="",
    )
    return "".join(f"{line}\n" for line in lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pumpkin_pristine.py",
        description="Diff the pumpkin.toml a Pumpkin build writes on first run with the Adapter's.",
    )
    parser.add_argument("binary", type=Path, help="the Pumpkin executable to run once")
    parser.add_argument(
        "--committed",
        type=Path,
        default=COMMITTED,
        metavar="FILE",
        help="the pumpkin.toml to diff against (default: the Adapter's)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        metavar="S",
        help=f"stop the binary after S seconds (default {DEFAULT_TIMEOUT:g})",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the binary as `argv` (`sys.argv[1:]` if None) says; return the exit code."""
    args = _build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    use_unshare = unshare_works()
    if not use_unshare:
        print(
            "unshare -rn is not available here: the binary ran with network access", file=sys.stderr
        )
    with tempfile.TemporaryDirectory(prefix="pumpkin-pristine-") as workdir:
        result = run_pristine(
            args.binary,
            Path(workdir),
            use_unshare=use_unshare,
            timeout=args.timeout,
            path=os.environ.get("PATH", ""),
        )
    if result.config is None:
        print(
            f"{args.binary} wrote no {CONFIG_NAME} within {args.timeout:g} s. Its output:\n"
            f"{result.output}",
            file=sys.stderr,
        )
        return 2
    diff = config_diff(args.committed.read_text(), result.config, fresh_name=str(args.binary))
    if not diff:
        print("no difference (ignoring seed)")
        return 0
    print(diff, end="")
    return 1


if __name__ == "__main__":
    sys.exit(main())
