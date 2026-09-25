import asyncio
import contextlib
import os
import sys
from collections.abc import Awaitable, Callable
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


@pytest.fixture
def tcp_probe() -> Probe:
    return accepts_tcp


@pytest.fixture
def is_alive() -> Callable[[int], bool]:
    return alive


@pytest.fixture
def fake_plan(tmp_path: Path) -> Callable[..., LaunchPlan]:
    """Build a LaunchPlan for tests/runner/fake_server.py on a free port, run in tmp_path.

    Positional arguments are fake_server flags; `stop_stdin` overrides the stop line.
    """

    def make(*flags: str, stop_stdin: bytes | None = b"stop\n") -> LaunchPlan:
        port = free_port()
        return LaunchPlan(
            # -I -S: isolated and without site, so it starts fast and sees only FAKE_ENV.
            argv=(sys.executable, "-I", "-S", str(FAKE_SERVER), str(port), *flags),
            cwd=tmp_path,
            env=FAKE_ENV,
            endpoint=Endpoint(host="127.0.0.1", port=port),
            stop_stdin=stop_stdin,
        )

    return make
