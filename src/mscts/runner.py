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
            ready_ns = await _ready_ns(ready, plan.endpoint)
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


async def _ready_ns(ready: Callable[[Endpoint], Awaitable[bool]], endpoint: Endpoint) -> int:
    """Poll `ready` until it returns True; return when it did."""
    while True:
        if await ready(endpoint):
            return time.monotonic_ns()
        await asyncio.sleep(_POLL_INTERVAL_S)


def _signal_group(process: asyncio.subprocess.Process, signum: signal.Signals) -> None:
    """Send `signum` to the process's whole group (its pid: it leads its own session)."""
    with contextlib.suppress(ProcessLookupError):  # the group is already gone
        os.killpg(process.pid, signum)
