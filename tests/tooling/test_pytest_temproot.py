"""Every pytest task gets its own temp root, so another run's cleanup cannot delete it (#298)."""

import os
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import cast

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "with_temproot.py"
PYTEST_TASKS = (
    "test",
    "test:reference",
    "test:selfcheck",
    "test:candidate",
    "test:statistical",
)
LIVE_TASKS = ("test:reference", "test:selfcheck", "test:candidate")
REPORT_ROOT = "import os, pathlib; print(pathlib.Path(os.environ['PYTEST_DEBUG_TEMPROOT']))"


def _run(*args: str, code: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_DEBUG_TEMPROOT"}
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args, "--", sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _tasks() -> dict[str, dict[str, str]]:
    with (ROOT / "mise.toml").open("rb") as file:
        return cast("dict[str, dict[str, str]]", tomllib.load(file)["tasks"])


@pytest.mark.parametrize("task", PYTEST_TASKS)
def test_each_pytest_task_runs_under_its_own_temp_root(task: str) -> None:
    run = _tasks()[task]["run"]

    assert "scripts/with_temproot.py" in run
    assert "pytest" in run
    assert "--basetemp" not in run


@pytest.mark.parametrize("task", LIVE_TASKS)
def test_live_tasks_keep_the_temp_root_when_the_run_fails(task: str) -> None:
    assert "--keep-on-failure" in _tasks()[task]["run"]


def test_the_command_gets_a_fresh_temp_root_that_is_removed_afterwards() -> None:
    first = _run(code=REPORT_ROOT)
    second = _run(code=REPORT_ROOT)

    root = Path(first.stdout.strip())
    assert first.returncode == 0
    assert root != Path(second.stdout.strip())
    assert not root.exists()


def test_the_temp_root_exists_while_the_command_runs() -> None:
    result = _run(
        code="import os, pathlib; print(pathlib.Path(os.environ['PYTEST_DEBUG_TEMPROOT']).is_dir())"
    )

    assert result.stdout.strip() == "True"


def test_a_failing_command_passes_its_status_through_and_loses_its_root() -> None:
    result = _run(code=REPORT_ROOT + "; raise SystemExit(3)")

    assert result.returncode == 3
    assert not Path(result.stdout.strip()).exists()


def test_keep_on_failure_keeps_the_root_of_a_failed_run_and_names_it() -> None:
    result = _run("--keep-on-failure", code=REPORT_ROOT + "; raise SystemExit(1)")

    root = Path(result.stdout.strip())
    try:
        assert result.returncode == 1
        assert root.is_dir()
        assert str(root) in result.stderr
    finally:
        if root.is_dir():
            root.rmdir()


def test_keep_on_failure_removes_the_root_of_a_passing_run() -> None:
    result = _run("--keep-on-failure", code=REPORT_ROOT)

    assert result.returncode == 0
    assert not Path(result.stdout.strip()).exists()
