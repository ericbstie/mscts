"""A killed harness's process groups are swept at the next Instance launch (#3)."""

import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path

import pytest
from support.leak_guard import kill_survivors

from mscts import runner
from mscts.adapters.base import LaunchPlan
from mscts.net import Endpoint
from mscts.runner import _guarded_group as guarded_group
from mscts.runner import _parent_guard as parent_guard
from mscts.runner import _sweep_orphans as sweep_orphans
from mscts.runner import running
from tests.runner import conftest as runner_fakes
from tests.runner.conftest import becomes_true

type Probe = Callable[[Endpoint], Awaitable[bool]]
type FakePlan = Callable[..., LaunchPlan]
_SOURCE = str(Path(runner.__file__).resolve().parents[1])


class _DisappearingStat:
    def read_text(self) -> str:
        raise ProcessLookupError


def test_a_process_reaped_during_the_stat_read_counts_as_dead(
    monkeypatch: pytest.MonkeyPatch, is_running: Callable[[int], bool]
) -> None:
    monkeypatch.setattr(runner_fakes, "Path", lambda _path: _DisappearingStat())
    try:
        alive = is_running(42)
    except ProcessLookupError:
        pytest.fail("the process disappeared during the read, so it is dead")
    assert not alive


_HARNESS = """
import asyncio, contextlib, json, os, sys
from pathlib import Path
from mscts.adapters.base import LaunchPlan
from mscts.net import Endpoint
from mscts.runner import running

async def probe(endpoint):
    try:
        _, writer = await asyncio.open_connection(endpoint.host, endpoint.port)
    except OSError:
        return False
    writer.close()
    await writer.wait_closed()
    return True

async def main():
    pids = []
    async with contextlib.AsyncExitStack() as stack:
        for fields in json.loads(sys.argv[1]):
            plan = LaunchPlan(
                argv=tuple(fields['argv']), cwd=Path(fields['cwd']),
                env=dict(os.environ), endpoint=Endpoint(fields['host'], fields['port']),
                stop_stdin=b'stop\\n',
            )
            instance = await stack.enter_async_context(running(plan, ready=probe, ready_timeout=5))
            lines = instance.log_path.read_text().splitlines()
            child_line = next(line for line in lines if line.startswith('child='))
            pids.extend([instance.pid, int(child_line.removeprefix('child='))])
        print(json.dumps(pids), flush=True)
        await asyncio.Event().wait()

asyncio.run(main())
"""


@pytest.mark.asyncio
async def test_next_launch_stops_the_groups_of_a_sigkilled_harness(
    fake_plan: FakePlan,
    tcp_probe: Probe,
    is_running: Callable[[int], bool],
) -> None:
    plan = fake_plan("--child")
    eof_plan = replace(fake_plan("--child", "--stop-on-eof"), cwd=plan.cwd / "eof")
    eof_plan.cwd.mkdir()
    next_plan = replace(fake_plan(), cwd=plan.cwd / "next")
    next_plan.cwd.mkdir()
    harness = await asyncio.create_subprocess_exec(
        sys.executable,
        "-S",
        "-c",
        _HARNESS,
        json.dumps(
            [
                {
                    "argv": item.argv,
                    "cwd": str(item.cwd),
                    "host": item.endpoint.host,
                    "port": item.endpoint.port,
                }
                for item in (plan, eof_plan)
            ]
        ),
        env={
            **plan.env,
            "MSCTS_CACHE": os.environ["MSCTS_CACHE"],
            "PYTHONPATH": _SOURCE,
        },
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        assert harness.stdout is not None
        async with asyncio.timeout(5):
            line = await harness.stdout.readline()
        assert line, "the helper harness did not yield its ready Instance"
        pids = json.loads(line)
        assert all(is_running(pid) for pid in pids)
        records = Path(os.environ["MSCTS_CACHE"]) / "instances"
        sweep_orphans(records)
        assert all(is_running(pid) for pid in pids)
        assert len(list(records.glob("*.guard"))) == 2
        harness.kill()
        await harness.wait()
        assert await becomes_true(lambda: not is_running(pids[2]))
        assert all(is_running(pids[index]) for index in (0, 1, 3))
        async with running(next_plan, ready=tcp_probe, ready_timeout=5):
            assert await becomes_true(lambda: not any(is_running(pid) for pid in pids))
            assert len(list(records.glob("*.guard"))) == 1
        assert not list(records.iterdir())
    finally:
        if harness.returncode is None:
            harness.kill()
        await harness.communicate()
        token = "MSCTS_FAKE_TOKEN=" + plan.env["MSCTS_FAKE_TOKEN"]
        leaked = kill_survivors(token, within=0)
        assert not leaked, f"processes outlived the proof: {leaked}"


def _write_process(proc: Path, pid: int, group: int, started: int, value: str) -> Path:
    process = proc / str(pid)
    process.mkdir(parents=True)
    fields = ["S", "5", str(group), str(group), *(["0"] * 15), str(started)]
    (process / "stat").write_text(f"{pid} (fake (server)) " + " ".join(fields))
    (process / "environ").write_bytes(f"OTHER=value\0MSCTS_INSTANCE_TOKEN={value}\0".encode())
    return process


@pytest.mark.parametrize("proof", ["valid", "wrong-start", "wrong-token", "token-prefix"])
def test_sweep_requires_the_recorded_start_time_and_exact_environment_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, proof: str
) -> None:
    value = "a" * 64
    proc = tmp_path / "proc"
    environment = value if proof in {"valid", "wrong-start"} else value + "x"
    if proof == "wrong-token":
        environment = "b" * 64
    _write_process(proc, 40, 40, 1000, environment)
    monkeypatch.setattr(runner.os, "getpgrp", lambda: 999)
    monkeypatch.setattr(runner, "PROC", proc)
    directory = tmp_path / "records"
    directory.mkdir()
    born = 999 if proof == "wrong-start" else 1000
    (directory / f"{value}.guard").write_text(f"40 {born}\n")
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(runner.os, "killpg", lambda group, signum: signals.append((group, signum)))

    sweep_orphans(directory)

    assert signals == ([(40, 9)] if proof == "valid" else [])
    assert not list(directory.iterdir())


def test_sweep_recovers_a_spawn_before_the_leader_was_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = "a" * 64
    proc = tmp_path / "proc"
    _write_process(proc, 40, 40, 1000, value)
    monkeypatch.setattr(runner.os, "getpgrp", lambda: 999)
    monkeypatch.setattr(runner, "PROC", proc)
    directory = tmp_path / "records"
    directory.mkdir()
    (directory / f"{value}.guard").write_text("")
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(runner.os, "killpg", lambda group, signum: signals.append((group, signum)))
    sweep_orphans(directory)
    assert signals == [(40, 9)]


@pytest.mark.parametrize("started", [999, 1001], ids=["older-foreign", "descendant"])
def test_a_leaderless_group_requires_a_tagged_member_no_older_than_the_leader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, started: int
) -> None:
    value = "a" * 64
    process = _write_process(tmp_path, 41, 40, started, value)
    monkeypatch.setattr(runner.os, "getpgrp", lambda: 999)
    monkeypatch.setattr(runner, "PROC", tmp_path)
    assert guarded_group(process, value, (40, 1000)) == (40 if started == 1001 else None)


def test_a_tagged_process_in_another_group_is_never_claimed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = "a" * 64
    process = _write_process(tmp_path, 41, 41, 1001, value)
    monkeypatch.setattr(runner.os, "getpgrp", lambda: 999)
    monkeypatch.setattr(runner, "PROC", tmp_path)
    assert guarded_group(process, value, (40, 1000)) is None


def test_a_malformed_record_is_retained_without_signaling_any_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    record = tmp_path / f"{'a' * 64}.guard"
    record.write_text("not a recorded process")
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(runner.os, "killpg", lambda group, signum: signals.append((group, signum)))
    sweep_orphans(tmp_path)
    assert not signals
    assert record.read_text() == "not a recorded process"
    assert "could not sweep Instance record" in caplog.text


def test_sweep_rejects_a_process_whose_identity_changes_while_reading_its_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = "a" * 64
    process = _write_process(tmp_path, 40, 40, 1000, value)
    monkeypatch.setattr(runner.os, "getpgrp", lambda: 999)
    identities = iter([(40, 40, 1000), (40, 40, 1001)])
    monkeypatch.setattr(runner, "_guard_stat", lambda _process: next(identities))
    assert guarded_group(process, value, None) is None


def test_locked_records_are_skipped_even_by_their_own_harness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "cache" / "instances"
    proc = tmp_path / "proc"
    proc.mkdir()
    monkeypatch.setattr(runner, "PROC", proc)
    monkeypatch.setattr(runner.os, "getpgrp", lambda: 999)
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(runner.os, "killpg", lambda group, signum: signals.append((group, signum)))
    with parent_guard() as first:
        _write_process(proc, 40, 40, 1000, first.value)
        first.record_process(40)
        assert len(list(directory.glob("*.guard"))) == 1
        with parent_guard():
            assert not signals
            assert len(list(directory.glob("*.guard"))) == 2
        assert len(list(directory.glob("*.guard"))) == 1
    assert not list(directory.iterdir())


@pytest.mark.asyncio
async def test_guard_is_armed_before_spawn_and_removed_when_launch_fails(
    fake_plan: FakePlan, tcp_probe: Probe, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "cache" / "instances"

    async def fail_launch(*_args: object, **_kwargs: object) -> None:
        assert len(list(directory.glob("*.guard"))) == 1
        msg = "deliberate launch failure"
        raise OSError(msg)

    monkeypatch.setattr(runner.asyncio, "create_subprocess_exec", fail_launch)
    with pytest.raises(runner.RunnerError, match="deliberate launch failure"):
        async with running(fake_plan(), ready=tcp_probe, ready_timeout=5):
            pytest.fail("nothing was launched")
    assert not list(directory.iterdir())


@pytest.mark.asyncio
async def test_a_guard_cache_that_cannot_be_written_fails_before_launch(
    fake_plan: FakePlan, tcp_probe: Probe, tmp_path: Path
) -> None:
    (tmp_path / "cache").write_text("a file where the cache directory should be")
    with pytest.raises(runner.RunnerError, match="could not guard Instance") as caught:
        async with running(fake_plan(), ready=tcp_probe, ready_timeout=5):
            pytest.fail("the unguarded Instance must not launch")
    assert caught.value.exit_code is None
    assert not (tmp_path / "mscts-console.log").exists()
