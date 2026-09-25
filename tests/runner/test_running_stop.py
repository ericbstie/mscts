import logging
import time
from collections.abc import Awaitable, Callable

import pytest

from mscts.adapters.base import LaunchPlan
from mscts.net import Endpoint
from mscts.runner import running

type Probe = Callable[[Endpoint], Awaitable[bool]]
type FakePlan = Callable[..., LaunchPlan]


@pytest.mark.asyncio
async def test_leaving_the_context_sends_the_stop_line_and_waits_for_a_graceful_exit(
    fake_plan: FakePlan,
    tcp_probe: Probe,
    is_alive: Callable[[int], bool],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="mscts.runner")
    plan = fake_plan()
    async with running(plan, ready=tcp_probe, ready_timeout=5, stop_timeout=5) as instance:
        leaving = time.monotonic()
    assert time.monotonic() - leaving < 1  # it exited at once; no timeout was waited out
    assert not is_alive(instance.pid)
    assert instance.log_path.read_text().splitlines()[-1] == "stopping"
    assert f"(pid {instance.pid}) stopped by stdin with exit code 0" in caplog.text
