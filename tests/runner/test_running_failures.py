import asyncio
import time
from collections.abc import Awaitable, Callable

import pytest

from mscts.adapters.base import LaunchPlan
from mscts.net import Endpoint
from mscts.runner import CONSOLE_LOG, RunnerError, running

type Probe = Callable[[Endpoint], Awaitable[bool]]
type FakePlan = Callable[..., LaunchPlan]


@pytest.mark.asyncio
async def test_a_process_that_exits_before_it_is_ready_raises_its_exit_code_and_log_tail(
    fake_plan: FakePlan, tcp_probe: Probe
) -> None:
    plan = fake_plan("--exit-early", "3")
    with pytest.raises(RunnerError) as caught:
        async with running(plan, ready=tcp_probe, ready_timeout=2):
            pytest.fail("the Instance was never ready")
    error = caught.value
    assert error.exit_code == 3
    assert error.log_path == plan.cwd / CONSOLE_LOG
    assert error.log_tail == tuple(f"line {number}" for number in range(11, 51))  # last 40
    assert "exited with code 3 before it was ready" in str(error)
    assert str(error).endswith("line 49\nline 50")


def _pid(error: RunnerError) -> int:
    """The fake server's pid, from the first line of its console."""
    return int(error.log_tail[0].removeprefix("pid="))


async def _never_answers(_endpoint: Endpoint) -> bool:
    await asyncio.sleep(3600)
    return True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("flags", "probe"),
    [(("--never-listen",), None), ((), _never_answers)],
    ids=["never-listens", "probe-hangs"],
)
async def test_not_ready_in_time_stops_the_process_before_it_raises(
    fake_plan: FakePlan,
    tcp_probe: Probe,
    is_alive: Callable[[int], bool],
    flags: tuple[str, ...],
    probe: Probe | None,
) -> None:
    plan = fake_plan(*flags)
    started = time.monotonic()
    with pytest.raises(RunnerError) as caught:
        async with running(plan, ready=probe or tcp_probe, ready_timeout=0.3):
            pytest.fail("the Instance was never ready")
    elapsed = time.monotonic() - started
    error = caught.value
    endpoint = f"{plan.endpoint.host}:{plan.endpoint.port}"
    assert f"not ready at {endpoint} within 0.3 s" in str(error)
    assert 0.3 <= elapsed < 1.5
    # Stopped before the error was built: its exit code is known, and it is gone.
    assert error.exit_code is not None
    assert not is_alive(_pid(error))


@pytest.mark.asyncio
async def test_a_probe_raising_timeout_error_is_not_mistaken_for_the_ready_timeout(
    fake_plan: FakePlan, tcp_probe: Probe, is_alive: Callable[[int], bool]
) -> None:
    plan = fake_plan()

    async def broken(endpoint: Endpoint) -> bool:
        if await tcp_probe(endpoint):  # listening, so it has logged its pid
            raise TimeoutError
        return False

    with pytest.raises(TimeoutError) as caught:
        async with running(plan, ready=broken, ready_timeout=5):
            pytest.fail("the Instance was never ready")
    assert not isinstance(caught.value, RunnerError)
    pid = int((plan.cwd / CONSOLE_LOG).read_text().splitlines()[0].removeprefix("pid="))
    assert not is_alive(pid)
