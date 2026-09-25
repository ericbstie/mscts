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
