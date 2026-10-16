"""scripts/research/lock_wait.py: the two series it times, and that it prints three timings."""

import importlib.util
import types
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "research" / "lock_wait.py"


@pytest.fixture(scope="module")
def lock_wait() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("research_lock_wait", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_per_run_series_asks_repeat_for_a_lock_per_run(lock_wait: types.ModuleType) -> None:
    command = lock_wait.series_command("per run", 4)
    assert Path(command[1]).name == "repeat.py"
    assert command[2:6] == ["--times", "4", "--live-lock", "--"]


def test_the_whole_series_runs_repeat_under_one_outer_lock(lock_wait: types.ModuleType) -> None:
    command = lock_wait.series_command("whole series", 4)
    assert Path(command[1]).name == "live_lock.py"
    assert command[2] == "--"
    assert Path(command[4]).name == "repeat.py"
    assert "--live-lock" not in command


def test_it_prints_the_free_time_and_each_series_wait(
    lock_wait: types.ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    lock_wait.main(["--runs", "2", "--run-seconds", "0.3", "--short-after", "0.1"])
    lines = capsys.readouterr().out.splitlines()
    assert [line.partition(":")[0] for line in lines] == [
        "short run, lock free",
        "whole series",
        "per run",
    ]
    assert all(line.endswith(" s") for line in lines)
