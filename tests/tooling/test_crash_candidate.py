"""scripts/research/crash_candidate.py: which process it kills as the crashing Candidate (#531)."""

import importlib.util
import signal
import subprocess
import sys
import types
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from tests.run.fakes import TOKEN_VAR

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "research" / "crash_candidate.py"

_SLEEPS = "import time; time.sleep(30)"


@pytest.fixture(scope="module")
def crash() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("research_crash_candidate", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def _sleeping_in(cwd: Path, token: str) -> Iterator[subprocess.Popen[bytes]]:
    """A process that sleeps in `cwd`, tagged with `token`, killed when the block ends."""
    cwd.mkdir(parents=True)
    process = subprocess.Popen(
        [sys.executable, "-I", "-S", "-c", _SLEEPS], cwd=cwd, env={TOKEN_VAR: token}
    )
    try:
        yield process
    finally:
        process.kill()
        process.wait()


def test_it_kills_the_one_process_in_a_candidate_directory_under_the_run(
    crash: types.ModuleType, run_token: str, tmp_path: Path
) -> None:
    with (
        _sleeping_in(tmp_path / "run/0/candidate", run_token) as candidate,
        _sleeping_in(tmp_path / "run/0/reference", run_token) as reference,
        _sleeping_in(tmp_path / "other/candidate", run_token) as other,
    ):
        killed = crash.kill_under(tmp_path / "run", "candidate")

        assert killed == candidate.pid
        assert candidate.wait(timeout=5) == -signal.SIGKILL
        assert reference.poll() is None
        assert other.poll() is None


def test_it_kills_nothing_when_more_than_one_process_could_be_the_candidate(
    crash: types.ModuleType, run_token: str, tmp_path: Path
) -> None:
    with (
        _sleeping_in(tmp_path / "run/0/candidate", run_token) as first,
        _sleeping_in(tmp_path / "run/1/candidate", run_token) as second,
    ):
        with pytest.raises(LookupError, match="2 processes run in a candidate directory"):
            crash.kill_under(tmp_path / "run", "candidate")

        assert first.poll() is None
        assert second.poll() is None
