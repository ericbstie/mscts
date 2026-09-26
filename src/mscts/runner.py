"""The one generic runner: launch any LaunchPlan, wait until it is ready, always stop it.

Server-agnostic by design (ADR-0004): it never parses logs, and readiness is decided by
an injected probe (in a Run, the status ping), plus proof that the socket answering at
the Endpoint is the Instance's own.

Linux only: that proof is read from /proc (see `_listeners` and `_group_sockets`).
"""

import asyncio
import contextlib
import ipaddress
import logging
import os
import re
import secrets
import signal
import socket
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from mscts.adapters.base import LaunchPlan
from mscts.net import Endpoint

# The Instance's console (stdout and stderr), written into the plan's cwd.
CONSOLE_LOG = "mscts-console.log"
# Between readiness probes. It bounds how late ready_ns can be.
_POLL_INTERVAL_S = 0.02
# How much of the console a RunnerError quotes.
LOG_TAIL_LINES = 40
_LOG_TAIL_BYTES = 64 * 1024  # read at most this much, however big the log grew
# Where the kernel shows who owns which socket. Linux's procfs; nothing else has it.
PROC = Path("/proc")
_TCP_LISTEN = 0x0A  # the `st` column of /proc/net/tcp for a listening socket
_SOCKET_LINK = re.compile(r"socket:\[(\d+)\]")  # what /proc/<pid>/fd/<n> points to

_log = logging.getLogger(__name__)


class RunnerError(RuntimeError):
    """An Instance could not be launched, exited before it was ready, or was not ready in time.

    `exit_code` is None if nothing was launched. It follows asyncio: negative means killed
    by that signal.
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


def free_endpoint() -> Endpoint:
    """An Endpoint for one Instance: a random loopback host of its own, and a port free on it.

    The host is 127.A.B.C with A in 1..254, B in 0..255 and C in 1..254: about 16.5
    million hosts, none in 127.0.0.0/16 (127.0.0.1, systemd's 127.0.0.53 and Debian's
    127.0.1.1 are everybody else's), and never the network or broadcast address. The
    port is one the kernel had free on that host a moment ago, from its ephemeral range.

    Collision odds: two Instances share a host with odds of 1 in 16.5 million (with 100
    alive at once, any two of them with about 3 in 10 000). Even then, both would also
    need the same port: the kernel hands a port out only while it is free on that host,
    so that takes the time-of-check race below, on top. And if it happened anyway, the
    Instance that did not bind would never be ready (the readiness ownership check), so
    a collision can fail a run but never make one Instance answer for another.

    Racy by nature (time of check to time of use): the port is released before this
    returns, and the Instance binds it only when it gets that far (vanilla: ~7 s after
    launch). Take it right before `prepare`, and launch at once.
    """
    a, b, c = 1 + secrets.randbelow(254), secrets.randbelow(256), 1 + secrets.randbelow(254)
    host = f"127.{a}.{b}.{c}"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as placeholder:
        placeholder.bind((host, 0))
        return Endpoint(host=host, port=int(placeholder.getsockname()[1]))


@dataclass(frozen=True, slots=True)
class Instance:
    """One running server process started from a LaunchPlan."""

    endpoint: Endpoint
    pid: int  # also its session and process-group id
    launched_ns: int  # time.monotonic_ns() just before the process was spawned
    ready_ns: int  # time.monotonic_ns() once a probe returned True and the Instance owned it
    log_path: Path  # its console: stdout and stderr, in the plan's cwd


@contextlib.asynccontextmanager
async def running(
    plan: LaunchPlan,
    *,
    ready: Callable[[Endpoint], Awaitable[bool]],
    ready_timeout: float,
    stop_timeout: float = 10.0,
) -> AsyncIterator[Instance]:
    """Launch `plan`, yield its Instance once `ready(endpoint)` is True, then stop it.

    `ready` is polled until it returns True; it returns False while the server is not
    ready yet. An answer counts only if the Instance provably gave it: the IPv4 sockets
    listening at exactly the Endpoint were the same before and after that probe, and
    each of them is open in a process of the Instance's process group (see
    `_listeners`). Otherwise another process answered, and polling goes on; if that
    lasts until `ready_timeout`, the RunnerError names who holds the socket. The
    process runs in its own session with exactly `plan.env`, stdin piped, and stdout
    and stderr in `log_path` (overwritten by each launch).

    On leaving the context, however the body ends (normally, by an exception, by
    cancellation), the process is stopped and reaped: `plan.stop_stdin` is written to
    stdin, which is then closed; after `stop_timeout` seconds the process group gets
    SIGTERM, and after another `stop_timeout`, SIGKILL. A plan without a stop line gets
    SIGTERM at once. Being cancelled again while stopping SIGKILLs it at once. How it
    stopped is logged.
    """
    log_path = plan.cwd / CONSOLE_LOG
    _check_ownership_is_provable(plan.endpoint, log_path)
    deadline = asyncio.get_running_loop().time() + ready_timeout
    try:
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
    except OSError as error:
        reason = f"could not launch {plan.argv[0]}: {error}"
        raise _failure(reason, None, log_path) from error
    try:
        readiness = asyncio.timeout_at(deadline)
        others = _OtherListeners(plan.endpoint)
        try:
            async with readiness:
                ready_ns = await _ready_ns(process, ready, plan.endpoint, others)
        except TimeoutError:
            if not readiness.expired():  # the probe's own TimeoutError: a probe bug
                raise
            exit_code = await _stop(process, plan, stop_timeout)
            host, port = plan.endpoint.host, plan.endpoint.port
            reason = f"{plan.argv[0]} was not ready at {host}:{port} within {ready_timeout} s"
            raise _failure(reason + others.explain(), exit_code, log_path) from None
        if ready_ns is None:
            reason = f"{plan.argv[0]} exited with code {process.returncode} before it was ready"
            raise _failure(reason + others.explain(), process.returncode, log_path)
        yield Instance(
            endpoint=plan.endpoint,
            pid=process.pid,
            launched_ns=launched_ns,
            ready_ns=ready_ns,
            log_path=log_path,
        )
    finally:
        await _stop(process, plan, stop_timeout)


async def _stop(process: asyncio.subprocess.Process, plan: LaunchPlan, stop_timeout: float) -> int:
    """Stop the process if it still runs, reap it, and return its exit code.

    Then SIGKILL whatever is left of its process group, so none of its children outlives
    it. While any member is left, the kernel keeps the group id allocated, so the kill
    reaches only them. Once none is, the kill finds no group, unless the pid space
    wrapped around and a new group leader took that id in the moment since the reap (at
    most one readiness probe long). That is negligible even with a small pid_max.
    """
    if process.returncode is not None:
        exit_code = process.returncode
    else:
        try:
            how = await _stop_steps(process, plan.stop_stdin, stop_timeout)
        except BaseException:
            # Cancelled again (a second Ctrl-C, a TaskGroup or loop shutting down) or
            # interrupted mid-stop: kill it now rather than leak it. asyncio's child
            # watcher reaps it as soon as the event loop runs again.
            _signal_group(process, signal.SIGKILL)
            raise
        exit_code = await process.wait()  # at once: it has exited
        graceful = how == ("stdin" if plan.stop_stdin is not None else "SIGTERM")
        _log.log(
            logging.INFO if graceful else logging.WARNING,
            "%s (pid %d) stopped by %s with exit code %d",
            *(plan.argv[0], process.pid, how, exit_code),
        )
    _signal_group(process, signal.SIGKILL)
    return exit_code


async def _stop_steps(
    process: asyncio.subprocess.Process, stop_stdin: bytes | None, stop_timeout: float
) -> str:
    """Stop the process, escalating after each `stop_timeout`; return what stopped it.

    The stop line (if any) and the closing of stdin, then SIGTERM to the process group,
    then SIGKILL to the process group.
    """
    if stop_stdin is not None and await _within(stop_timeout, _ask_to_stop(process, stop_stdin)):
        return "stdin"
    if process.stdin is not None:
        process.stdin.close()
    _signal_group(process, signal.SIGTERM)
    if await _within(stop_timeout, process.wait()):
        return "SIGTERM"
    _signal_group(process, signal.SIGKILL)
    await process.wait()
    return "SIGKILL"


async def _ask_to_stop(process: asyncio.subprocess.Process, stop_stdin: bytes) -> None:
    """Write `stop_stdin`, close stdin, and wait for the process to exit."""
    if process.stdin is not None:  # always: stdin is piped
        with contextlib.suppress(ConnectionError):  # it has already closed its end
            process.stdin.write(stop_stdin)
            await process.stdin.drain()
        process.stdin.close()
    await process.wait()


async def _within(seconds: float, work: Awaitable[object]) -> bool:
    """Whether `work` finished within `seconds` (it is cancelled if not)."""
    try:
        async with asyncio.timeout(seconds):
            await work
    except TimeoutError:
        return False
    return True


@dataclass
class _OtherListeners:
    """The last time a probe answered True but the Instance was not proven to answer it.

    Kept for the RunnerError, to say who listened at the Endpoint instead.
    """

    endpoint: Endpoint
    listeners: frozenset[int] | None = None  # None: no probe has answered True yet
    not_ours: frozenset[int] = field(default_factory=frozenset)

    def explain(self) -> str:
        """Why a probe that answered did not make the Instance ready ("" if none did)."""
        where = f"{self.endpoint.host}:{self.endpoint.port}"
        if self.listeners is None:
            return ""
        if not self.listeners:
            return f"; a probe was answered, but no IPv4 socket listens at exactly {where}"
        if not self.not_ours:
            return f"; a probe was answered, but the sockets listening at {where} changed"
        owners = ", ".join(_owners(self.not_ours)) or "a process this user cannot see"
        return f"; a probe was answered, but a socket listening at {where} is held by {owners}"


async def _ready_ns(
    process: asyncio.subprocess.Process,
    ready: Callable[[Endpoint], Awaitable[bool]],
    endpoint: Endpoint,
    others: _OtherListeners,
) -> int | None:
    """Poll `ready` until the Instance itself answers True; return when; None if it exits.

    An answer is the Instance's only if there were sockets listening at the Endpoint,
    the same ones before and after the probe (so the one that answered is among them),
    and every one of them is open in the Instance's process group. Otherwise `others`
    records who did listen there.
    """
    while True:
        before = _listeners(endpoint)
        answer = await ready(endpoint)
        if process.returncode is not None:
            return None
        if answer:
            after = _listeners(endpoint)
            ours = _group_sockets(process.pid)
            if after and after == before and after <= ours:
                return time.monotonic_ns()
            others.listeners = before | after
            others.not_ours = others.listeners - ours
        await asyncio.sleep(_POLL_INTERVAL_S)


def _check_ownership_is_provable(endpoint: Endpoint, log_path: Path) -> None:
    """Raise unless `_listeners` can tell who listens at `endpoint`, before launching.

    RunnerError off Linux (no /proc/net/tcp); ValueError if the host is no IPv4 address.
    """
    _tcp_address(endpoint)
    if not (PROC / "net" / "tcp").is_file():
        reason = (
            f"cannot prove who listens at {endpoint.host}:{endpoint.port}: readiness reads "
            f"socket owners from Linux's {PROC}/net/tcp, which {sys.platform} does not have"
        )
        raise RunnerError(reason, exit_code=None, log_path=log_path, log_tail=())


def _tcp_address(endpoint: Endpoint) -> str:
    """`endpoint` as /proc/net/tcp writes a local address: `%08X:%04X`.

    The first word is the address in network byte order, printed as a native-endian
    integer (127.0.0.1 is 0100007F on x86); the second is the port.
    """
    word = int.from_bytes(ipaddress.IPv4Address(endpoint.host).packed, sys.byteorder)
    return f"{word:08X}:{endpoint.port:04X}"


def _listeners(endpoint: Endpoint) -> frozenset[int]:
    """The inodes of the IPv4 TCP sockets listening at exactly `endpoint`.

    From /proc/net/tcp, which lists this network namespace's sockets. Whenever there is
    such a socket, a connection to the Endpoint reaches one of them, because the kernel
    prefers a listener bound to the exact address to a wildcard (0.0.0.0) one. There
    are several only with SO_REUSEPORT, and then the kernel spreads connections over
    all of them. A wildcard or IPv6 listener is never counted: a server must bind its
    loopback Endpoint exactly (an IPv6 one would need /proc/net/tcp6, which this
    container's kernel lacks).
    """
    address = _tcp_address(endpoint)
    inodes: set[int] = set()
    for line in (PROC / "net" / "tcp").read_text().splitlines()[1:]:
        # sl local_address rem_address st tx:rx tr:when retrnsmt uid timeout inode ...
        columns = line.split()
        if columns[1] == address and int(columns[3], 16) == _TCP_LISTEN:
            inodes.add(int(columns[9]))
    return frozenset(inodes)


def _processes() -> list[Path]:
    """The /proc/<pid> directory of every process visible here."""
    return [entry for entry in PROC.iterdir() if entry.name.isdigit()]


def _process_group(process: Path) -> int | None:
    """The process group id of the process at `process` (/proc/<pid>), None if it is gone."""
    try:
        stat = (process / "stat").read_text()
    except OSError:
        return None
    # "pid (comm) state ppid pgrp ...": comm may hold spaces and parentheses.
    return int(stat.rpartition(")")[2].split()[2])


def _sockets(process: Path) -> frozenset[int]:
    """The inodes of the sockets open in the process at `process` (/proc/<pid>)."""
    inodes: set[int] = set()
    try:
        descriptors = list((process / "fd").iterdir())
    except OSError:  # gone, or not ours to read
        descriptors = []
    for descriptor in descriptors:
        try:
            link = descriptor.readlink()
        except OSError:  # closed meanwhile
            continue
        if match := _SOCKET_LINK.fullmatch(str(link)):
            inodes.add(int(match[1]))
    return frozenset(inodes)


def _group_sockets(pgid: int) -> frozenset[int]:
    """The inodes of the sockets open in any process of process group `pgid`.

    Every member counts, not just its leader: a server may listen from a child.
    """
    inodes: set[int] = set()
    for process in _processes():
        if _process_group(process) == pgid:
            inodes |= _sockets(process)
    return frozenset(inodes)


def _owners(inodes: frozenset[int]) -> list[str]:
    """Who holds any of `inodes`, as "pid N (name)", among the processes visible here."""
    owners = []
    for process in _processes():
        if _sockets(process) & inodes:
            with contextlib.suppress(OSError):  # gone meanwhile
                owners.append(f"pid {process.name} ({(process / 'comm').read_text().strip()})")
    return owners


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
