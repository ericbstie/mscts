"""Readiness needs ownership: the socket listening at the Endpoint is the Instance's own.

Without it, a probe answered by another server at the same Endpoint (another worker's
Instance, an orphan, anything) makes a Scenario run against the wrong server, and
`instance.startup` read milliseconds (audit H1, docs/audits/2026-09-26-foundation.md).
"""

import asyncio
import dataclasses
import os
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from mscts import runner
from mscts.adapters.base import LaunchPlan
from mscts.net import Endpoint
from mscts.runner import CONSOLE_LOG, RunnerError, running

type Probe = Callable[[Endpoint], Awaitable[bool]]
type FakePlan = Callable[..., LaunchPlan]
type Eventually = Callable[[Callable[[], bool]], Awaitable[bool]]


async def _hang_up(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    writer.close()


def _console(plan: LaunchPlan) -> str:
    console = plan.cwd / CONSOLE_LOG
    return console.read_text() if console.exists() else ""


@pytest.mark.asyncio
async def test_a_probe_answered_by_another_process_never_makes_the_instance_ready(
    fake_plan: FakePlan, tcp_probe: Probe
) -> None:
    plan = fake_plan("--never-listen")
    host, port = plan.endpoint.host, plan.endpoint.port
    # The impostor is this test's own process: it answers every probe at the Endpoint.
    impostor = await asyncio.start_server(_hang_up, host, port)
    async with impostor:
        with pytest.raises(RunnerError) as caught:
            async with running(plan, ready=tcp_probe, ready_timeout=0.2):
                pytest.fail("ready, although the impostor answered every probe")
    error = caught.value
    assert f"not ready at {host}:{port} within 0.2 s" in error.reason
    assert f"held by pid {os.getpid()} (" in error.reason  # names who holds the socket
    assert error.exit_code is not None  # the Instance was stopped before the error


@pytest.mark.asyncio
async def test_a_socket_shared_with_another_process_is_not_the_instance_s_own(
    fake_plan: FakePlan, tcp_probe: Probe
) -> None:
    # With SO_REUSEPORT both listen at the Endpoint, and the kernel spreads connections
    # over the two: an answer may be either's.
    plan = fake_plan("--reuseport")
    host, port = plan.endpoint.host, plan.endpoint.port
    impostor = await asyncio.start_server(_hang_up, host, port, reuse_port=True)
    async with impostor:

        async def once_both_listen(endpoint: Endpoint) -> bool:
            return "listening" in _console(plan) and await tcp_probe(endpoint)

        with pytest.raises(RunnerError) as caught:
            async with running(plan, ready=once_both_listen, ready_timeout=0.3):
                pytest.fail("ready, although the impostor listens at the Endpoint too")
    assert f"held by pid {os.getpid()} (" in caught.value.reason


@pytest.mark.asyncio
async def test_a_probe_answering_true_with_nothing_listening_at_the_endpoint_is_not_ready(
    fake_plan: FakePlan,
) -> None:
    plan = fake_plan("--never-listen")

    async def says_yes(_endpoint: Endpoint) -> bool:
        return True

    with pytest.raises(RunnerError) as caught:
        async with running(plan, ready=says_yes, ready_timeout=0.1):
            pytest.fail("ready, although nothing listens at the Endpoint")
    where = f"{plan.endpoint.host}:{plan.endpoint.port}"
    assert f"no IPv4 socket listens at exactly {where}" in caught.value.reason


@pytest.mark.asyncio
async def test_a_probe_answered_while_the_listener_changed_hands_does_not_count(
    fake_plan: FakePlan, tcp_probe: Probe, eventually: Eventually
) -> None:
    # The impostor answers the first probe, then gives the Endpoint up to the Instance
    # before that probe returns. Only a later probe, answered by the Instance, counts.
    plan = fake_plan("--listen-after", "0.2")  # well after the impostor has closed
    impostor = await asyncio.start_server(_hang_up, plan.endpoint.host, plan.endpoint.port)
    attempts: list[bool] = []

    async def handing_over(endpoint: Endpoint) -> bool:
        answer = await tcp_probe(endpoint)
        if not attempts:
            impostor.close()
            await impostor.wait_closed()
            assert await eventually(lambda: "listening" in _console(plan))
        attempts.append(answer)
        return answer

    async with impostor, running(plan, ready=handing_over, ready_timeout=5):
        assert len(attempts) >= 2
        assert attempts[0]  # the impostor did answer the first probe


@pytest.mark.asyncio
async def test_a_listener_in_a_child_of_the_instance_s_process_group_is_its_own(
    fake_plan: FakePlan, tcp_probe: Probe
) -> None:
    plan = fake_plan("--listen-in-child")
    async with running(plan, ready=tcp_probe, ready_timeout=5) as instance:
        lines = _console(plan).splitlines()
        (listener,) = (int(line.removeprefix("listener=")) for line in lines if "listener=" in line)
        assert listener != instance.pid
        assert os.getpgid(listener) == instance.pid


@pytest.mark.asyncio
async def test_off_linux_running_refuses_before_launching(
    fake_plan: FakePlan, tcp_probe: Probe, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(runner, "PROC", tmp_path / "no-proc")  # as on macOS: no /proc/net/tcp
    plan = fake_plan()
    with pytest.raises(RunnerError, match="Linux") as caught:
        async with running(plan, ready=tcp_probe, ready_timeout=5):
            pytest.fail("ready without any way to tell who listens at the Endpoint")
    assert caught.value.exit_code is None
    assert not (plan.cwd / CONSOLE_LOG).exists()  # nothing was launched


@pytest.mark.asyncio
async def test_an_endpoint_host_that_is_no_ipv4_address_is_refused_before_launching(
    fake_plan: FakePlan, tcp_probe: Probe
) -> None:
    plan = fake_plan()
    plan = dataclasses.replace(plan, endpoint=Endpoint(host="localhost", port=plan.endpoint.port))
    with pytest.raises(ValueError, match="localhost"):
        async with running(plan, ready=tcp_probe, ready_timeout=5):
            pytest.fail("ready without any way to tell who listens at the Endpoint")
    assert not (plan.cwd / CONSOLE_LOG).exists()
