"""Whatever ends the body, the Instance is stopped and reaped: no orphan is left behind."""

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from mscts.adapters.base import LaunchPlan
from mscts.net import Endpoint
from mscts.runner import CONSOLE_LOG, running

type Probe = Callable[[Endpoint], Awaitable[bool]]
type FakePlan = Callable[..., LaunchPlan]
type Eventually = Callable[[Callable[[], bool]], Awaitable[bool]]

GUARD_S = 5  # no test here should come near it; it only turns a hang into a failure


class BodyError(Exception):
    pass


def _logged_pid(console: Path) -> int | None:
    """The fake server's pid once it has logged it (its first, complete line)."""
    first, newline, _ = console.read_text().partition("\n") if console.exists() else ("", "", "")
    return int(first.removeprefix("pid=")) if newline else None


@pytest.mark.asyncio
async def test_an_exception_in_the_body_stops_the_instance_and_propagates_unchanged(
    fake_plan: FakePlan, tcp_probe: Probe, is_alive: Callable[[int], bool]
) -> None:
    plan = fake_plan()
    error = BodyError("from the body")
    pids: list[int] = []

    async def use() -> None:
        async with running(plan, ready=tcp_probe, ready_timeout=5) as instance:
            pids.append(instance.pid)
            raise error

    with pytest.raises(BodyError) as caught:
        await use()
    assert caught.value is error
    assert not is_alive(pids[0])
    assert (plan.cwd / CONSOLE_LOG).read_text().splitlines()[-1] == "stopping"  # gracefully


@pytest.mark.asyncio
async def test_cancelling_the_task_during_the_body_stops_the_instance(
    fake_plan: FakePlan, tcp_probe: Probe, is_alive: Callable[[int], bool]
) -> None:
    plan = fake_plan()
    instances: asyncio.Queue[int] = asyncio.Queue()

    async def use() -> None:
        async with running(plan, ready=tcp_probe, ready_timeout=5) as instance:
            instances.put_nowait(instance.pid)
            await asyncio.sleep(3600)

    async with asyncio.timeout(GUARD_S):
        task = asyncio.create_task(use())
        pid = await instances.get()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert not is_alive(pid)
    assert (plan.cwd / CONSOLE_LOG).read_text().splitlines()[-1] == "stopping"


@pytest.mark.asyncio
async def test_a_timeout_around_the_body_stops_the_instance(
    fake_plan: FakePlan, tcp_probe: Probe, is_alive: Callable[[int], bool]
) -> None:
    plan = fake_plan()
    pids: list[int] = []

    async def use() -> None:
        async with running(plan, ready=tcp_probe, ready_timeout=5) as instance:
            pids.append(instance.pid)
            await asyncio.sleep(3600)

    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.3):
            await use()
    assert not is_alive(pids[0])


@pytest.mark.asyncio
async def test_cancelling_the_task_while_it_waits_for_readiness_stops_the_process(
    fake_plan: FakePlan, is_alive: Callable[[int], bool]
) -> None:
    plan = fake_plan("--never-listen")
    console = plan.cwd / CONSOLE_LOG
    launched = asyncio.Event()

    async def not_yet(_endpoint: Endpoint) -> bool:
        if _logged_pid(console) is not None:
            launched.set()
        return False

    async def use() -> None:
        async with running(plan, ready=not_yet, ready_timeout=GUARD_S):
            pytest.fail("the Instance was never ready")

    async with asyncio.timeout(GUARD_S):
        task = asyncio.create_task(use())
        await launched.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    pid = _logged_pid(console)
    assert pid is not None
    assert not is_alive(pid)


@pytest.mark.asyncio
async def test_cancelling_again_during_the_stop_kills_the_process_at_once(
    fake_plan: FakePlan,
    tcp_probe: Probe,
    is_alive: Callable[[int], bool],
    eventually: Eventually,
) -> None:
    # It ignores the stop line and SIGTERM, and the stop_timeout is long: without the
    # second cancellation, stopping it would take two stop_timeouts.
    plan = fake_plan("--ignore-stop", "--ignore-sigterm")
    console = plan.cwd / CONSOLE_LOG
    instances: asyncio.Queue[int] = asyncio.Queue()

    async def use() -> None:
        async with running(
            plan, ready=tcp_probe, ready_timeout=5, stop_timeout=GUARD_S
        ) as instance:
            instances.put_nowait(instance.pid)
            await asyncio.sleep(3600)

    async with asyncio.timeout(GUARD_S):
        task = asyncio.create_task(use())
        pid = await instances.get()
        task.cancel()  # starts the stop
        assert await eventually(lambda: "ignoring stop" in console.read_text())
        task.cancel()  # interrupts it
        with pytest.raises(asyncio.CancelledError):
            await task
    assert await eventually(lambda: not is_alive(pid))  # killed, and reaped by the loop
