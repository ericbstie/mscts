import asyncio
import contextlib
import os
import signal
import sys
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator, Mapping
from pathlib import Path
from types import MappingProxyType

import pytest

from mscts.adapters.base import LaunchPlan
from mscts.net import Endpoint
from mscts.runner import free_port

FAKE_SERVER = Path(__file__).with_name("fake_server.py")
FAKE_ENV = MappingProxyType({"FAKE_ENV": "from-the-plan"})

type Probe = Callable[[Endpoint], Awaitable[bool]]


async def accepts_tcp(endpoint: Endpoint) -> bool:
    """A readiness probe: something accepts TCP connections at `endpoint`."""
    try:
        _, writer = await asyncio.open_connection(endpoint.host, endpoint.port)
    except OSError:
        return False
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    return True


def alive(pid: int) -> bool:
    """Whether `pid` still exists (running, or a zombie nobody has reaped)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _state(pid: int) -> str | None:
    """The process state from /proc (R, S, Z, ...), or None if there is no such process."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except FileNotFoundError:
        return None
    return stat.rpartition(")")[2].split()[0]


def runs(pid: int) -> bool:
    """Whether `pid` is still running: it exists and has not exited (is no zombie)."""
    return _state(pid) not in {None, "Z", "X"}


async def becomes_true(predicate: Callable[[], bool], within: float = 1.0) -> bool:
    """Whether `predicate` holds within `within` seconds, while the event loop runs.

    For what settles a moment later: a killed process takes a moment to exit, asyncio's
    child watcher reaps our child on a later loop iteration, and PID 1 (lazy in this
    container) reaps a grandchild whenever it gets round to it.
    """
    deadline = time.monotonic() + within
    while not predicate():
        if time.monotonic() > deadline:
            return False
        await asyncio.sleep(0.01)
    return True


@pytest.fixture
def tcp_probe() -> Probe:
    return accepts_tcp


@pytest.fixture
def is_alive() -> Callable[[int], bool]:
    return alive


@pytest.fixture
def is_running() -> Callable[[int], bool]:
    return runs


@pytest.fixture
def eventually() -> Callable[[Callable[[], bool]], Awaitable[bool]]:
    return becomes_true


def _running_with(variable: bytes) -> list[int]:
    """The running processes whose environment holds `variable` (NAME=value)."""
    pids = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            environ = (entry / "environ").read_bytes()  # empty for a zombie
        except OSError:  # gone meanwhile
            continue
        if variable in environ.split(b"\0"):
            pids.append(int(entry.name))
    return pids


@pytest.fixture
def fake_env() -> Iterator[Mapping[str, str]]:
    """FAKE_ENV plus a token for this test; fails the test if a tagged process outlives it.

    Every process a fake server starts inherits the token, so this catches leaks the
    runner under test (red, or regressed) would otherwise leave behind, and kills them.
    """
    token = f"MSCTS_FAKE_TOKEN={uuid.uuid4().hex}"
    yield MappingProxyType({**FAKE_ENV, "MSCTS_FAKE_TOKEN": token.partition("=")[2]})
    deadline = time.monotonic() + 1  # a process just killed takes a moment to exit
    while (leaked := _running_with(token.encode())) and time.monotonic() < deadline:
        time.sleep(0.01)
    for pid in leaked:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
    assert not leaked, f"fake server processes outlived the test: {leaked}"


@pytest.fixture
def fake_plan(tmp_path: Path, fake_env: Mapping[str, str]) -> Callable[..., LaunchPlan]:
    """Build a LaunchPlan for tests/runner/fake_server.py on a free port, run in tmp_path.

    Positional arguments are fake_server flags; `stop_stdin` overrides the stop line.
    """

    def make(*flags: str, stop_stdin: bytes | None = b"stop\n") -> LaunchPlan:
        port = free_port()
        return LaunchPlan(
            # -I -S: isolated and without site, so it starts fast and sees only fake_env.
            argv=(sys.executable, "-I", "-S", str(FAKE_SERVER), str(port), *flags),
            cwd=tmp_path,
            env=fake_env,
            endpoint=Endpoint(host="127.0.0.1", port=port),
            stop_stdin=stop_stdin,
        )

    return make
