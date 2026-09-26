import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

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


STOP_TIMEOUT = 0.3


@dataclass(frozen=True, slots=True)
class Escalation:
    flags: tuple[str, ...]  # fake_server flags
    stop_stdin: bytes | None
    stopped_by: str
    exit_code: int
    timeouts: int  # how many stop_timeouts it waits out first
    level: int  # of the log record saying how it stopped


ESCALATIONS = {
    # A stop line it ignores: SIGTERM after one stop_timeout, then SIGKILL after two.
    "ignores-stop": Escalation(("--ignore-stop",), b"stop\n", "SIGTERM", -15, 1, logging.WARNING),
    "ignores-stop-and-sigterm": Escalation(
        ("--ignore-stop", "--ignore-sigterm"), b"stop\n", "SIGKILL", -9, 2, logging.WARNING
    ),
    # No stop line: SIGTERM is the graceful stop, so it comes at once.
    "no-stop-line": Escalation((), None, "SIGTERM", -15, 0, logging.INFO),
    "no-stop-line-ignores-sigterm": Escalation(
        ("--ignore-sigterm",), None, "SIGKILL", -9, 1, logging.WARNING
    ),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ESCALATIONS.values(), ids=ESCALATIONS.keys())
async def test_the_stop_escalates_to_sigterm_then_sigkill_of_the_process_group(
    fake_plan: FakePlan,
    tcp_probe: Probe,
    is_alive: Callable[[int], bool],
    caplog: pytest.LogCaptureFixture,
    case: Escalation,
) -> None:
    caplog.set_level(logging.INFO, logger="mscts.runner")
    plan = fake_plan(*case.flags, stop_stdin=case.stop_stdin)
    async with running(
        plan, ready=tcp_probe, ready_timeout=5, stop_timeout=STOP_TIMEOUT
    ) as instance:
        leaving = time.monotonic()
    waited = time.monotonic() - leaving
    # It waited out exactly `timeouts` stop_timeouts: the step before gave up, the next
    # one never came.
    assert case.timeouts * STOP_TIMEOUT <= waited < (case.timeouts + 1) * STOP_TIMEOUT
    assert not is_alive(instance.pid)
    (record,) = (r for r in caplog.records if f"(pid {instance.pid}) stopped" in r.getMessage())
    expected = f"stopped by {case.stopped_by} with exit code {case.exit_code}"
    assert record.getMessage().endswith(expected)
    assert record.levelno == case.level
    console = instance.log_path.read_text().splitlines()
    assert ("ignoring stop" in console) == ("--ignore-stop" in case.flags)
    assert ("ignoring SIGTERM" in console) == ("--ignore-sigterm" in case.flags)  # got SIGTERM


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stop_stdin",
    [None, b"stop\n"],
    ids=["sigterm-reaches-the-child", "the-child-outlives-a-graceful-exit"],
)
async def test_no_process_of_the_instance_s_group_outlives_the_stop(
    fake_plan: FakePlan,
    tcp_probe: Probe,
    is_running: Callable[[int], bool],
    eventually: Callable[[Callable[[], bool]], Awaitable[bool]],
    stop_stdin: bytes | None,
) -> None:
    plan = fake_plan("--child", stop_stdin=stop_stdin)
    async with running(
        plan, ready=tcp_probe, ready_timeout=5, stop_timeout=STOP_TIMEOUT
    ) as instance:
        console = instance.log_path.read_text().splitlines()
        (child,) = (int(line.removeprefix("child=")) for line in console if "child=" in line)
        assert is_running(child)
        assert os.getpgid(child) == instance.pid
    assert await eventually(lambda: not is_running(child))
