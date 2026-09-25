"""The one generic runner: launch any LaunchPlan, wait until it is ready, always stop it.

Server-agnostic by design (ADR-0004): it never parses logs, and readiness is decided by
an injected probe (in a Run, the status ping).
"""

import asyncio
import contextlib
import os
import signal
import socket
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from mscts.adapters.base import LaunchPlan
from mscts.net import Endpoint

LOOPBACK = "127.0.0.1"
# The Instance's console (stdout and stderr), written into the plan's cwd.
CONSOLE_LOG = "mscts-console.log"
# Between readiness probes. It bounds how late ready_ns can be.
_POLL_INTERVAL_S = 0.02
# How much of the console a RunnerError quotes.
LOG_TAIL_LINES = 40
_LOG_TAIL_BYTES = 64 * 1024  # read at most this much, however big the log grew


class RunnerError(RuntimeError):
    """An Instance could not be started: it exited before it was ready, or never was.

    `exit_code` follows asyncio: negative means killed by that signal.
    """

    def __init__(
        self, reason: str, *, exit_code: int | None, log_path: Path, log_tail: tuple[str, ...]
    ) -> None:
        """Explain `reason`, quoting the last lines of the Instance's console."""
        self.reason = reason
        self.exit_code = exit_code
        self.log_path = log_path
        self.log_tail = log_tail
        quote = "\n".join((f"--- last {len(log_tail)} lines of {log_path} ---", *log_tail))
        super().__init__(f"{reason}\n{quote}")


def free_port() -> int:
    """A TCP port on 127.0.0.1 that nothing had bound a moment ago.

    The kernel picks it from its ephemeral range, so it is never a well-known port such as
    25565, and consecutive calls rarely repeat.

    It is racy by nature (time of check to time of use): the port is released before this
    returns, so another process, such as another worker's server, can take it before the
    Instance binds it. The Instance then fails to bind and exits before it is ready, or,
    worse, the readiness probe reaches the other process. Keep the gap short: take the
    port right before `prepare` and launch at once.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as placeholder:
        placeholder.bind((LOOPBACK, 0))
        return int(placeholder.getsockname()[1])


@dataclass(frozen=True, slots=True)
class Instance:
    """One running server process started from a LaunchPlan."""

    endpoint: Endpoint
    pid: int  # also its session and process-group id
    launched_ns: int  # time.monotonic_ns() just before the process was spawned
    ready_ns: int  # time.monotonic_ns() when the readiness probe first returned True
    log_path: Path  # its console: stdout and stderr, in the plan's cwd


@contextlib.asynccontextmanager
async def running(
    plan: LaunchPlan,
    *,
    ready: Callable[[Endpoint], Awaitable[bool]],
    ready_timeout: float,
) -> AsyncIterator[Instance]:
    """Launch `plan`, yield its Instance once `ready(endpoint)` is True, then stop it.

    `ready` is polled until it returns True; it returns False while the server is not
    ready yet. The process runs in its own session with exactly `plan.env`, stdin piped,
    and stdout and stderr in `log_path` (overwritten by each launch).
    """
    log_path = plan.cwd / CONSOLE_LOG
    deadline = asyncio.get_running_loop().time() + ready_timeout
    with log_path.open("wb") as console:
        launched_ns = time.monotonic_ns()
        process = await asyncio.create_subprocess_exec(
            *plan.argv,
            cwd=plan.cwd,
            env=dict(plan.env),
            stdin=asyncio.subprocess.PIPE,
            stdout=console,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
    try:
        async with asyncio.timeout_at(deadline):
            ready_ns = await _ready_ns(process, ready, plan.endpoint)
        if ready_ns is None:
            reason = f"{plan.argv[0]} exited with code {process.returncode} before it was ready"
            raise _failure(reason, process.returncode, log_path)
        yield Instance(
            endpoint=plan.endpoint,
            pid=process.pid,
            launched_ns=launched_ns,
            ready_ns=ready_ns,
            log_path=log_path,
        )
    finally:
        _signal_group(process, signal.SIGKILL)
        await process.wait()


async def _ready_ns(
    process: asyncio.subprocess.Process,
    ready: Callable[[Endpoint], Awaitable[bool]],
    endpoint: Endpoint,
) -> int | None:
    """Poll `ready` until it returns True and return when it did; None if the process exits."""
    while True:
        answer = await ready(endpoint)
        if process.returncode is not None:
            return None
        if answer:
            return time.monotonic_ns()
        await asyncio.sleep(_POLL_INTERVAL_S)


def _failure(reason: str, exit_code: int | None, log_path: Path) -> RunnerError:
    return RunnerError(reason, exit_code=exit_code, log_path=log_path, log_tail=_log_tail(log_path))


def _log_tail(log_path: Path) -> tuple[str, ...]:
    """The last LOG_TAIL_LINES lines of the console, or none if it cannot be read."""
    try:
        with log_path.open("rb") as log:
            size = log.seek(0, os.SEEK_END)
            log.seek(max(0, size - _LOG_TAIL_BYTES))
            text = log.read().decode(errors="replace")
    except OSError:
        return ()
    return tuple(text.splitlines()[-LOG_TAIL_LINES:])


def _signal_group(process: asyncio.subprocess.Process, signum: signal.Signals) -> None:
    """Send `signum` to the process's whole group (its pid: it leads its own session)."""
    with contextlib.suppress(ProcessLookupError):  # the group is already gone
        os.killpg(process.pid, signum)
