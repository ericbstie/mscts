#!/usr/bin/env python3
"""Run a command under the live-tier lock (#138).

The wrapper holds the descriptor while the command runs, then explicitly unlocks it.
The command inherits a copy so it keeps the lock if the wrapper is killed (#138).
A `live_lock.py` started inside a holder's command runs straight through (#411).
"""

import argparse
import contextlib
import fcntl
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator, MutableMapping
from pathlib import Path
from types import FrameType
from typing import cast

from mscts import install
from mscts.adapters.base import Adapter, ProvisionError
from mscts.adapters.pumpkin import PumpkinAdapter
from mscts.adapters.vanilla import VanillaAdapter
from mscts.cache import cache_dir
from mscts.target import TARGET

# A holder exports its pid under this name to its command, which then takes no lock (#411).
HELD_VARIABLE = "MSCTS_LIVE_LOCK_HELD"

# The Adapter whose Installation each live tier needs (as tests/support/tiers.py NEEDS).
TIER_ADAPTERS: dict[str, type[Adapter]] = {
    "reference": VanillaAdapter,
    "selfcheck": VanillaAdapter,
    "candidate": PumpkinAdapter,
}


@contextlib.contextmanager
def _queue_mutex(queue: Path) -> Iterator[None]:
    """Serialise changes to the queue: a ticket is never seen before it is locked."""
    descriptor = os.open(queue / "mutex", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def _tickets(queue: Path) -> list[str]:
    """The tickets in arrival order: a number from a counter, then the waiter's pid."""
    return sorted(entry.name for entry in queue.iterdir() if entry.name != "mutex")


def _take_ticket(queue: Path) -> tuple[Path, int]:
    """Join the back of the queue. The waiter holds a flock on its ticket until it leaves.

    A ticket whose flock is free belongs to a waiter that died, so it is not waited for.
    """
    with _queue_mutex(queue):
        last = max((int(name.partition("-")[0]) for name in _tickets(queue)), default=0)
        ticket = queue / f"{last + 1:012d}-{os.getpid()}"
        descriptor = os.open(ticket, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
    return ticket, descriptor


def _waiter_is_dead(ticket: Path) -> bool:
    """Whether nobody holds `ticket`'s flock: its waiter died, or has left the queue."""
    try:
        descriptor = os.open(ticket, os.O_RDWR)
    except FileNotFoundError:
        return True
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    finally:
        os.close(descriptor)
    return True


def _live_ticket_ahead(queue: Path, mine: str) -> str | None:
    """The first ticket ahead of `mine` whose waiter is alive; the dead ones are removed."""
    with _queue_mutex(queue):
        for name in _tickets(queue):
            if name >= mine:
                return None
            if not _waiter_is_dead(queue / name):
                return name
            (queue / name).unlink(missing_ok=True)
    return None


def _wait_for_ticket(ticket: Path) -> None:
    """Block until the waiter holding `ticket` has taken the lock, or died."""
    try:
        descriptor = os.open(ticket, os.O_RDWR)
    except FileNotFoundError:
        return
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
    finally:
        os.close(descriptor)


def _say_waiting(pid: str) -> None:
    print(f"waiting for another live tier to finish (pid {pid})", file=sys.stderr, flush=True)


def _take_lock(descriptor: int, queue: Path) -> None:
    """Take the lock in the order waiters arrived (#374).

    Only the head of the queue asks for the lock, so a newcomer cannot slip in ahead of a
    waiter that `flock` has woken but not yet scheduled.
    """
    ticket, ticket_descriptor = _take_ticket(queue)
    try:
        while True:
            ahead = _live_ticket_ahead(queue, ticket.name)
            if ahead is not None:
                _say_waiting(ahead.partition("-")[2])
                _wait_for_ticket(queue / ahead)
                continue
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.lseek(descriptor, 0, os.SEEK_SET)
                holder = os.read(descriptor, 64).strip()
                if holder.isdigit():
                    _say_waiting(holder.decode("ascii"))
                    fcntl.flock(descriptor, fcntl.LOCK_EX)
                    return
                # The first holder has acquired the lock but has not published its pid (#138).
                time.sleep(0.01)
            else:
                return
    finally:
        ticket.unlink(missing_ok=True)
        os.close(ticket_descriptor)


def _write_pid(descriptor: int, pid: int) -> None:
    holder = f"{pid}\n".encode("ascii")
    os.pwrite(descriptor, holder, 0)
    os.ftruncate(descriptor, len(holder))


@contextlib.contextmanager
def hold_live_lock(cache: Path, environ: MutableMapping[str, str]) -> Iterator[int | None]:
    """Hold the live-tier lock in `cache` for the block, and yield its descriptor.

    A command started in the block inherits the descriptor (`pass_fds`), so it keeps the
    lock if its parent is killed (#138). Leaving the block names no pid and unlocks.

    `environ` names the holder to the block's commands (`HELD_VARIABLE`): one that asks
    for the lock again is inside this hold, so it takes nothing and gets `None`. So does a
    bypassed hold (`MSCTS_LIVE_LOCK=0`).
    """
    if environ.get("MSCTS_LIVE_LOCK") == "0" or HELD_VARIABLE in environ:
        yield None
        return
    queue = cache / "live-tier.queue"
    queue.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(cache / "live-tier.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        _take_lock(descriptor, queue)
        _write_pid(descriptor, os.getpid())
        environ[HELD_VARIABLE] = str(os.getpid())
        yield descriptor
    finally:
        environ.pop(HELD_VARIABLE, None)
        os.ftruncate(descriptor, 0)  # a waiter must never name a finished holder's pid
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


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


def _require_installation(tier: str) -> None:
    """Exit 1 with the install command if `tier`'s Installation is missing (ADR-0008).

    Checked before the lock, so a missing Installation does not wait behind another tier.
    """
    try:
        install.require(TIER_ADAPTERS[tier](), TARGET, cache_dir())
    except ProvisionError as error:
        sys.exit(str(error))


def main() -> None:
    """Lock the shared cache unless bypassed, run the command, then pass its status through."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", choices=sorted(TIER_ADAPTERS), help="the live tier to check")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    command = cast("list[str]", arguments.command)
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("a command is required after --")
    if arguments.tier is not None:
        _require_installation(arguments.tier)
    with hold_live_lock(cache_dir(), os.environ) as descriptor:
        code = _run_command(command, descriptor)
    if code < 0:
        if -code != signal.SIGKILL:
            signal.signal(-code, signal.SIG_DFL)
        os.kill(os.getpid(), -code)
    sys.exit(code)


if __name__ == "__main__":
    main()
