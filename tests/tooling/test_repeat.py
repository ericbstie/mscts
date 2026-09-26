"""scripts/repeat.py: argument handling, and that its stress processes always get cleaned up.

Hermetic: no real pytest subprocess anywhere (a fake `run` stands in for `run_once`), and
`stress_load`'s own processes are trivial busy loops this test starts and always confirms
gone, using the leak-guard pattern (tests/support/leak_guard.py).
"""

import importlib.util
import types
import uuid
from pathlib import Path

import pytest

_REPEAT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "repeat.py"


def _load_repeat() -> types.ModuleType:
    """Load scripts/repeat.py by path (scripts/ is not an importable package)."""
    spec = importlib.util.spec_from_file_location("repeat", _REPEAT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def repeat() -> types.ModuleType:
    return _load_repeat()


# -- split_argv / parse_args -------------------------------------------------------


def test_split_argv_splits_on_the_first_double_dash(repeat: types.ModuleType) -> None:
    own, pytest_args = repeat.split_argv(["--times", "5", "--", "-k", "foo"])
    assert own == ["--times", "5"]
    assert pytest_args == ["-k", "foo"]


def test_split_argv_raises_without_a_double_dash(repeat: types.ModuleType) -> None:
    with pytest.raises(repeat.RepeatError, match="--"):
        repeat.split_argv(["--times", "5"])


def test_parse_args_defaults_to_one_run_no_stress(repeat: types.ModuleType) -> None:
    args = repeat.parse_args(["--", "tests/"])
    assert args.pytest_args == ("tests/",)
    assert args.times == 1
    assert args.stress is False
    assert args.stress_workers >= 1  # os.cpu_count() or 1


def test_parse_args_reads_times_and_stress(repeat: types.ModuleType) -> None:
    args = repeat.parse_args(["--times", "20", "--stress", "--stress-workers", "3", "--", "tests/"])
    assert args.times == 20
    assert args.stress is True
    assert args.stress_workers == 3


def test_parse_args_rejects_no_pytest_args(repeat: types.ModuleType) -> None:
    with pytest.raises(repeat.RepeatError, match="no pytest arguments"):
        repeat.parse_args(["--times", "5", "--"])


def test_parse_args_rejects_non_positive_times(repeat: types.ModuleType) -> None:
    with pytest.raises(repeat.RepeatError, match="--times"):
        repeat.parse_args(["--times", "0", "--", "tests/"])


def test_parse_args_rejects_non_positive_stress_workers(repeat: types.ModuleType) -> None:
    with pytest.raises(repeat.RepeatError, match="--stress-workers"):
        repeat.parse_args(["--stress-workers", "0", "--", "tests/"])


# -- run_repeats / print_report (a fake `run`, no real pytest) ----------------------


def test_run_repeats_counts_passes_and_failures(repeat: types.ModuleType) -> None:
    outcomes: list[tuple[int, frozenset[str]]] = [
        (0, frozenset()),
        (1, frozenset({"tests/x.py::test_a"})),
        (0, frozenset()),
    ]

    def fake_run(_uv: str, _pytest_args: object) -> tuple[int, frozenset[str]]:
        return outcomes.pop(0)

    result = repeat.run_repeats("uv", ("tests/",), 3, run=fake_run)

    assert result.times == 3
    assert result.passed == 2
    assert result.failed == 1
    assert result.failing_ids == frozenset({"tests/x.py::test_a"})


def test_run_repeats_unions_failing_ids_across_runs(repeat: types.ModuleType) -> None:
    outcomes: list[tuple[int, frozenset[str]]] = [(1, frozenset({"a"})), (1, frozenset({"a", "b"}))]

    def fake_run(_uv: str, _pytest_args: object) -> tuple[int, frozenset[str]]:
        return outcomes.pop(0)

    result = repeat.run_repeats("uv", ("tests/",), 2, run=fake_run)

    assert result.failed == 2
    assert result.failing_ids == frozenset({"a", "b"})


def test_print_report_exit_code_is_zero_only_if_nothing_failed(
    repeat: types.ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    clean = repeat.RepeatResult(times=5, passed=5, failed=0, failing_ids=frozenset())
    assert repeat.print_report(clean) == 0

    dirty = repeat.RepeatResult(times=5, passed=4, failed=1, failing_ids=frozenset({"t"}))
    assert repeat.print_report(dirty) == 1
    out = capsys.readouterr().out
    assert "t" in out


def test_failing_ids_in_reads_pytest_s_failed_summary_lines(repeat: types.ModuleType) -> None:
    stdout = (
        "..F\n"
        "=== FAILURES ===\n"
        "=== short test summary info ===\n"
        "FAILED tests/x.py::test_a - AssertionError: boom\n"
        "FAILED tests/y.py::test_b[case0] - ValueError\n"
        "1 failed, 2 passed in 0.01s\n"
    )
    assert repeat.failing_ids_in(stdout) == frozenset(
        {"tests/x.py::test_a", "tests/y.py::test_b[case0]"}
    )


# -- stress_load: its processes always get cleaned up -------------------------------


def test_stress_load_starts_and_always_cleans_up_its_processes(repeat: types.ModuleType) -> None:
    token = uuid.uuid4().hex
    with repeat.stress_load(2, token) as processes:
        assert len(processes) == 2
        assert len(repeat.tagged_pids(f"MSCTS_REPEAT_STRESS={token}")) == 2
    assert repeat.tagged_pids(f"MSCTS_REPEAT_STRESS={token}") == []


def test_stress_load_cleans_up_even_when_the_block_raises(repeat: types.ModuleType) -> None:
    token = uuid.uuid4().hex

    class BoomError(Exception):
        pass

    with pytest.raises(BoomError), repeat.stress_load(2, token):
        raise BoomError

    assert repeat.tagged_pids(f"MSCTS_REPEAT_STRESS={token}") == []
