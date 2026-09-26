import asyncio
import dataclasses
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

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


@pytest.mark.asyncio
async def test_the_log_tail_is_read_from_the_last_64_kib_of_the_console_only(
    fake_plan: FakePlan, tcp_probe: Probe
) -> None:
    # A 10 MiB console that ends in one long line with no line break: reading all of it
    # would quote the numbered lines before that line too.
    plan = fake_plan("--exit-early", "3", "--flood", str(10 * 2**20))
    with pytest.raises(RunnerError) as caught:
        async with running(plan, ready=tcp_probe, ready_timeout=2):
            pytest.fail("the Instance was never ready")
    assert caught.value.log_tail == ("x" * 64 * 1024,)


@pytest.mark.asyncio
async def test_a_probe_answering_true_after_the_process_exited_is_not_ready(
    fake_plan: FakePlan, tcp_probe: Probe, is_running: Callable[[int], bool]
) -> None:
    # Its child still listens, in the Instance's process group, so the answer is the
    # Instance's own: only the exit itself says that the Instance is gone.
    plan = fake_plan("--listen-in-child", "--exit-early", "3")
    console = plan.cwd / CONSOLE_LOG

    async def once_it_exited(endpoint: Endpoint) -> bool:
        lines = console.read_text().splitlines() if console.exists() else []
        if not lines or "listening" not in lines or is_running(_pid_in(lines)):
            return False
        await asyncio.sleep(0.1)  # meanwhile asyncio's child watcher reaps it
        return await tcp_probe(endpoint)

    with pytest.raises(RunnerError) as caught:
        async with running(plan, ready=once_it_exited, ready_timeout=5):
            pytest.fail("ready, although the Instance's process had exited")
    assert caught.value.exit_code == 3
    assert "exited with code 3 before it was ready" in caught.value.reason


def _pid_in(console: list[str]) -> int:
    """The fake server's pid, from the first line of its console."""
    return int(console[0].removeprefix("pid="))


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["argv0", "cwd"])
async def test_a_plan_that_cannot_be_launched_raises_runner_error_without_an_exit_code(
    fake_plan: FakePlan, tcp_probe: Probe, tmp_path: Path, missing: str
) -> None:
    plan = fake_plan()
    nowhere = tmp_path / "nowhere"
    if missing == "argv0":
        plan = dataclasses.replace(plan, argv=(str(nowhere), *plan.argv[1:]))
    else:
        plan = dataclasses.replace(plan, cwd=nowhere)
    with pytest.raises(RunnerError, match="could not launch") as caught:
        async with running(plan, ready=tcp_probe, ready_timeout=5):
            pytest.fail("the Instance was never ready")
    assert caught.value.exit_code is None
    assert isinstance(caught.value.__cause__, FileNotFoundError)


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
