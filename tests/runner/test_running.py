import json
import os
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from mscts.adapters.base import LaunchPlan
from mscts.net import Endpoint
from mscts.runner import CONSOLE_LOG, running

type Probe = Callable[[Endpoint], Awaitable[bool]]
type FakePlan = Callable[..., LaunchPlan]


@pytest.mark.asyncio
async def test_running_yields_the_instance_once_the_probe_first_answers_true(
    fake_plan: FakePlan, tcp_probe: Probe, is_alive: Callable[[int], bool]
) -> None:
    plan = fake_plan("--listen-after", "0.2")
    probes: list[tuple[int, int, bool]] = []  # started_ns, ended_ns, answer

    async def ready(endpoint: Endpoint) -> bool:
        assert endpoint == plan.endpoint
        started_ns = time.monotonic_ns()
        answer = await tcp_probe(endpoint)
        probes.append((started_ns, time.monotonic_ns(), answer))
        return answer

    before_ns = time.monotonic_ns()
    async with running(plan, ready=ready, ready_timeout=5) as instance:
        answers = [answer for _, _, answer in probes]
        first_true = answers.index(True)
        assert first_true > 0  # it polled
        # The first True counts unless the server bound its socket during that very probe
        # (it was not listening yet just before it): then the next probe is the first
        # whose answer is provably the Instance's own.
        assert answers[first_true:] in ([True], [True, True])
        assert before_ns <= instance.launched_ns <= probes[0][0]
        # ready_ns: just before the probe that made it ready started, and after the one
        # before it ended. So none of that probe's own round trip (connect, handshake,
        # status) counts as startup (audit L6).
        assert probes[-2][1] <= instance.ready_ns <= probes[-1][0]
        assert instance.ready_ns - instance.launched_ns >= 200_000_000  # --listen-after 0.2
        assert instance.endpoint == plan.endpoint
        assert instance.log_path == plan.cwd / CONSOLE_LOG
        assert is_alive(instance.pid)
        # In its own session and process group, so it can be signalled as a whole and
        # a terminal's Ctrl-C reaches the harness, not the server.
        assert os.getsid(instance.pid) == os.getpgid(instance.pid) == instance.pid
    assert not is_alive(instance.pid)


@pytest.mark.asyncio
async def test_the_instance_runs_the_plan_in_its_cwd_with_only_its_env_and_logs_its_console(
    fake_plan: FakePlan, tcp_probe: Probe, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MSCTS_HARNESS_ONLY", "must not leak")
    plan = fake_plan()
    async with running(plan, ready=tcp_probe, ready_timeout=5) as instance:
        lines = instance.log_path.read_text().splitlines()
    assert instance.log_path.parent == tmp_path == plan.cwd
    assert f"pid={instance.pid}" in lines
    assert f"cwd={tmp_path}" in lines
    assert "hello from stderr" in lines  # stderr goes to the same file
    (env_line,) = (line for line in lines if line.startswith("env="))
    env = json.loads(env_line.removeprefix("env="))
    assert env["FAKE_ENV"] == "from-the-plan"
    assert "MSCTS_HARNESS_ONLY" not in env
