#!/usr/bin/env python3
"""Run a command with its own pytest temp root, so other runs' cleanup cannot delete it (#298).

Pytest keeps its base directories in `/tmp/pytest-of-<user>/` and, when a run ends, deletes all
but the newest few. Concurrent runs share that folder, so one deletes what another still uses.
`PYTEST_DEBUG_TEMPROOT` moves the folder: this makes a fresh one for the command and removes it
afterwards. A `--basetemp` the caller passes still wins, and the fresh folder is then empty.

`--keep-on-failure` keeps the folder when the command fails and names it, because the live tiers
keep a failing play's timelines in it.
"""

import argparse
import contextlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from types import FrameType
from typing import cast


def _run_command(command: list[str], root: Path) -> int:
    process: subprocess.Popen[bytes] | None = None
    pending: list[int] = []

    def forward(number: int, _frame: FrameType | None) -> None:
        if process is None:
            pending.append(number)
        else:
            with contextlib.suppress(ProcessLookupError):
                process.send_signal(number)

    previous = {
        number: signal.signal(number, forward) for number in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        env = {**os.environ, "PYTEST_DEBUG_TEMPROOT": str(root)}
        with subprocess.Popen(command, env=env) as process:  # noqa: S603 - explicit argv
            for number in pending:
                process.send_signal(number)
            return process.wait()
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def main() -> None:
    """Run the command in a fresh temp root, clean up, then pass its status through."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-on-failure", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    command = cast("list[str]", arguments.command)
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("a command is required after --")
    root = Path(tempfile.mkdtemp(prefix="mscts-pytest-"))
    code = 1
    try:
        code = _run_command(command, root)
    finally:
        if arguments.keep_on_failure and code != 0:
            print(f"kept the pytest temp root: {root}", file=sys.stderr)
        else:
            shutil.rmtree(root, ignore_errors=True)
    sys.exit(code if code >= 0 else 128 - code)


if __name__ == "__main__":
    main()
