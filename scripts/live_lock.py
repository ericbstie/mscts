#!/usr/bin/env python3
"""Run a command under the live-tier lock (#138).

The wrapper holds the descriptor while the command runs, then explicitly unlocks it.
The command inherits a copy so it keeps the lock if the wrapper is killed (#138).
"""

import argparse
import contextlib
import fcntl
import os
import signal
import subprocess
import sys
import time
from types import FrameType
from typing import cast

from mscts.cache import cache_dir


def _take_lock(descriptor: int) -> None:
    while True:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.lseek(descriptor, 0, os.SEEK_SET)
            holder = os.read(descriptor, 64).strip()
            if holder.isdigit():
                print(
                    f"waiting for another live tier to finish (pid {holder.decode('ascii')})",
                    file=sys.stderr,
                    flush=True,
                )
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                return
            # The first holder has acquired the lock but has not published its pid (#138).
            time.sleep(0.01)
        else:
            return


def _write_pid(descriptor: int, pid: int) -> None:
    holder = f"{pid}\n".encode("ascii")
    os.pwrite(descriptor, holder, 0)
    os.ftruncate(descriptor, len(holder))


def _signal_group(process: subprocess.Popen[bytes], number: int) -> None:
    """Signal the command's whole group: `uv run` ignores SIGINT and waits for its child.

    The command is in its own session, so a terminal's Ctrl-C never reaches it directly.
    """
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, number)


def _run_command(command: list[str], descriptor: int | None = None) -> int:
    process: subprocess.Popen[bytes] | None = None
    pending: list[int] = []

    def forward(number: int, _frame: FrameType | None) -> None:
        if process is None:
            pending.append(number)
        else:
            _signal_group(process, number)

    previous = {
        number: signal.signal(number, forward) for number in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        inherited = () if descriptor is None else (descriptor,)
        with subprocess.Popen(  # noqa: S603 - explicit argv, no shell
            command, start_new_session=True, pass_fds=inherited
        ) as process:
            if descriptor is not None:
                _write_pid(descriptor, process.pid)
            for number in pending:
                _signal_group(process, number)
            return process.wait()
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def main() -> None:
    """Lock the shared cache unless bypassed, run the command, then pass its status through."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    command = cast("list[str]", parser.parse_args().command)
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("a command is required after --")
    if os.environ.get("MSCTS_LIVE_LOCK") == "0":
        code = _run_command(command)
    else:
        cache = cache_dir()
        cache.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(cache / "live-tier.lock", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            _take_lock(descriptor)
            _write_pid(descriptor, os.getpid())
            code = _run_command(command, descriptor)
        finally:
            os.ftruncate(descriptor, 0)  # a waiter must never name a finished holder's pid
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
    if code < 0:
        if -code != signal.SIGKILL:
            signal.signal(-code, signal.SIG_DFL)
        os.kill(os.getpid(), -code)
    sys.exit(code)


if __name__ == "__main__":
    main()
