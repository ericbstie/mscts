"""scripts/repeat.py: argument handling, and that its stress processes always get cleaned up.

Hermetic: no real pytest subprocess anywhere (a fake `run` stands in for `run_once`), and
`stress_load`'s own processes are trivial busy loops this test starts and always confirms
gone, using the leak-guard pattern (tests/support/leak_guard.py).
"""

import contextlib
import fcntl
import importlib.util
import os
import select
import signal
import subprocess
import sys
import time
import types
import uuid
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from support.leak_guard import kill_survivors

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


def test_a_progress_line_is_visible_in_a_file_before_the_next_run(
    repeat: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "repeat.log"
    calls = 0

    def fake_run(_uv: str, _args: object) -> tuple[int, frozenset[str]]:
        nonlocal calls
        if calls:
            assert "run 1/2: exit code 0, 0 failing" in output.read_text()
        calls += 1
        return 0, frozenset[str]()

    with output.open("w") as stream, monkeypatch.context() as patch:
        patch.setattr(sys, "stdout", stream)
        repeat.run_repeats("uv", (), 2, run=fake_run)
    assert calls == 2


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
    tag = f"MSCTS_REPEAT_STRESS={token}"
    with repeat.stress_load(2, token) as processes:
        assert len(processes) == 2
        # A child's /proc environ shows the tag only once it has exec'd: wait for both.
        deadline = time.monotonic() + 10
        while len(repeat.tagged_pids(tag)) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(repeat.tagged_pids(tag)) == 2
    assert repeat.tagged_pids(f"MSCTS_REPEAT_STRESS={token}") == []


def test_stress_load_cleans_up_even_when_the_block_raises(repeat: types.ModuleType) -> None:
    token = uuid.uuid4().hex

    class BoomError(Exception):
        pass

    with pytest.raises(BoomError), repeat.stress_load(2, token):
        raise BoomError

    assert repeat.tagged_pids(f"MSCTS_REPEAT_STRESS={token}") == []


# -- --live-lock: the lock is taken for each run (#411) -----------------------------


def test_parse_args_reads_live_lock(repeat: types.ModuleType) -> None:
    assert repeat.parse_args(["--", "tests/"]).live_lock is False
    assert repeat.parse_args(["--live-lock", "--", "tests/"]).live_lock is True


def _recorded(events: list[str], name: str, value: int | None = None) -> Callable[[], Any]:
    @contextlib.contextmanager
    def scope() -> Iterator[int | None]:
        events.append(f"{name} in")
        try:
            yield value
        finally:
            events.append(f"{name} out")

    return scope


def _run_recording(events: list[str]) -> Callable[..., tuple[int, frozenset[str]]]:
    def run(_uv: str, _args: object, inherit: Sequence[int]) -> tuple[int, frozenset[str]]:
        events.append(f"run {tuple(inherit)}")
        return 3, frozenset({"t"})

    return run


def test_a_locked_run_takes_the_lock_then_the_load_around_the_run_only(
    repeat: types.ModuleType,
) -> None:
    events: list[str] = []
    locked = repeat.locked_run(
        _run_recording(events), hold=_recorded(events, "lock", 7), load=_recorded(events, "load")
    )
    assert locked("uv", ("t",)) == (3, frozenset({"t"}))
    assert events == ["lock in", "load in", "run (7,)", "load out", "lock out"]


def test_a_locked_run_with_nothing_to_inherit_passes_no_descriptor(
    repeat: types.ModuleType,
) -> None:
    events: list[str] = []
    locked = repeat.locked_run(
        _run_recording(events), hold=_recorded(events, "lock"), load=_recorded(events, "load")
    )
    locked("uv", ("t",))
    assert "run ()" in events


def test_a_series_releases_the_lock_between_two_runs(repeat: types.ModuleType) -> None:
    events: list[str] = []
    locked = repeat.locked_run(
        _run_recording(events), hold=_recorded(events, "lock", 7), load=_recorded(events, "load")
    )
    repeat.run_repeats("uv", ("t",), 2, run=locked)
    assert [event for event in events if event.startswith("lock")] == [
        "lock in",
        "lock out",
        "lock in",
        "lock out",
    ]
    assert events.index("lock out") < events.index("lock in", 1)


_STAND_IN_UV = """
import fcntl, os, sys
from pathlib import Path

def lock_state():
    try:
        with (Path(os.environ["MSCTS_CACHE"]) / "live-tier.lock").open("r+") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return "locked"
            return "free"
    except FileNotFoundError:
        return "free"

def stress_processes():
    count = 0
    mine = ("MSCTS_REPEAT_TEST=" + os.environ["MSCTS_REPEAT_TEST"]).encode()
    for entry in Path("/proc").iterdir():
        try:
            environ = (entry / "environ").read_bytes().split(b"\\0")
            if mine in environ and any(e.startswith(b"MSCTS_REPEAT_STRESS=") for e in environ):
                count += 1
        except OSError:
            pass
    return count

with open(os.environ["STAND_IN_LOG"], "a") as log:
    held_by = os.environ.get("MSCTS_LIVE_LOCK_HELD", "-")
    print(lock_state(), stress_processes(), held_by, file=log, flush=True)
if os.environ["STAND_IN_HOLDS"]:
    sys.stdin.read()
"""


class _Series:
    """A `repeat.py` process on a stand-in `uv`, which logs what it saw when each run began."""

    def __init__(self, tmp_path: Path, *, holds_run: bool) -> None:
        self.cache = tmp_path / "cache"
        self.log = tmp_path / "runs.log"
        self.holds_run = holds_run
        self.token = uuid.uuid4().hex
        self.stand_in = tmp_path / "bin" / "uv"
        self.stand_in.parent.mkdir()
        self.stand_in.write_text(f"#!{sys.executable}\n{_STAND_IN_UV}")
        self.stand_in.chmod(0o755)

    def start(self, *arguments: str) -> subprocess.Popen[str]:
        env = {key: value for key, value in os.environ.items() if key != "MSCTS_LIVE_LOCK_HELD"}
        env |= {
            "PATH": f"{self.stand_in.parent}{os.pathsep}{env['PATH']}",
            "MSCTS_CACHE": str(self.cache),
            "MSCTS_LIVE_LOCK": "1",
            "MSCTS_REPEAT_TEST": self.token,
            "STAND_IN_LOG": str(self.log),
            "STAND_IN_HOLDS": "1" if self.holds_run else "",
        }
        return subprocess.Popen(
            [sys.executable, str(_REPEAT_PATH), *arguments, "--", "tests/"],
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

    def runs(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []


@contextlib.contextmanager
def _series(
    tmp_path: Path, *, holds_run: bool = False
) -> Iterator[tuple[_Series, Callable[..., subprocess.Popen[str]]]]:
    series = _Series(tmp_path, holds_run=holds_run)
    processes: list[subprocess.Popen[str]] = []

    def start(*arguments: str) -> subprocess.Popen[str]:
        processes.append(series.start(*arguments))
        return processes[-1]

    try:
        yield series, start
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                assert stream is not None
                stream.close()
        assert kill_survivors(f"MSCTS_REPEAT_TEST={series.token}") == []


def _finish(process: subprocess.Popen[str]) -> int:
    process.communicate(timeout=30)
    return process.wait()


def test_a_live_lock_series_runs_every_run_under_the_lock(tmp_path: Path) -> None:
    with _series(tmp_path) as (series, start):
        process = start("--times", "2", "--live-lock")
        assert _finish(process) == 0
        assert series.runs() == [f"locked 0 {process.pid}"] * 2
        assert (series.cache / "live-tier.lock").read_text() == ""


def test_a_series_without_the_flag_takes_no_lock(tmp_path: Path) -> None:
    with _series(tmp_path) as (series, start):
        assert _finish(start("--times", "2")) == 0
        assert series.runs() == ["free 0 -", "free 0 -"]
        assert not (series.cache / "live-tier.lock").exists()


def test_stress_runs_during_each_run_of_a_live_lock_series(tmp_path: Path) -> None:
    with _series(tmp_path) as (series, start):
        arguments = ("--times", "2", "--live-lock", "--stress", "--stress-workers", "2")
        process = start(*arguments)
        assert _finish(process) == 0
        assert series.runs() == [f"locked 2 {process.pid}"] * 2


def test_stress_without_the_flag_covers_the_series_with_no_lock(tmp_path: Path) -> None:
    with _series(tmp_path) as (series, start):
        assert _finish(start("--times", "2", "--stress", "--stress-workers", "1")) == 0
        assert series.runs() == ["free 1 -", "free 1 -"]


def _stress_processes(token: str) -> int:
    """The stress processes of the series tagged `token`: other workers' series may run too."""
    count = 0
    mine = f"MSCTS_REPEAT_TEST={token}".encode()
    for entry in Path("/proc").iterdir():
        try:
            environ = (entry / "environ").read_bytes().split(b"\0")
            if mine in environ and any(e.startswith(b"MSCTS_REPEAT_STRESS=") for e in environ):
                count += 1
        except OSError:
            continue
    return count


def test_stress_does_not_run_while_the_series_waits_for_the_lock(tmp_path: Path) -> None:
    with _series(tmp_path) as (series, start):
        series.cache.mkdir()
        with (series.cache / "live-tier.lock").open("w") as other_holder:
            fcntl.flock(other_holder, fcntl.LOCK_EX)
            other_holder.write(str(os.getpid()))
            other_holder.flush()
            process = start("--live-lock", "--stress", "--stress-workers", "1")
            assert process.stderr is not None
            ready, _, _ = select.select([process.stderr], [], [], 10)
            assert ready, "the series did not say it was waiting"
            assert process.stderr.readline().startswith("waiting for another live tier")
            assert _stress_processes(series.token) == 0
            assert series.runs() == []
        assert _finish(process) == 0
        assert series.runs() == [f"locked 1 {process.pid}"]


def test_an_interrupted_series_keeps_the_holders_pid_in_place(tmp_path: Path) -> None:
    with _series(tmp_path) as (series, start):
        series.cache.mkdir()
        with (series.cache / "live-tier.lock").open("w") as other_holder:
            fcntl.flock(other_holder, fcntl.LOCK_EX)
            other_holder.write(f"{os.getpid()}\n")
            other_holder.flush()
            process = start("--live-lock")
            assert process.stderr is not None
            ready, _, _ = select.select([process.stderr], [], [], 10)
            assert ready, "the series did not say it was waiting"
            assert process.stderr.readline().startswith("waiting for another live tier")
            process.send_signal(signal.SIGINT)
            assert process.wait(timeout=10) != 0
            assert (series.cache / "live-tier.lock").read_text().strip() == str(os.getpid())
            assert series.runs() == []


def test_killing_a_series_keeps_the_lock_until_its_run_exits(tmp_path: Path) -> None:
    with _series(tmp_path, holds_run=True) as (series, start):
        process = start("--live-lock")
        deadline = time.monotonic() + 10
        while not series.runs():
            assert time.monotonic() < deadline, "the run never started"
            time.sleep(0.01)
        process.kill()
        process.wait(timeout=5)
        with (series.cache / "live-tier.lock").open("r+") as lock:
            with pytest.raises(BlockingIOError):
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert process.stdin is not None
            process.stdin.close()
            deadline = time.monotonic() + 10
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    assert time.monotonic() < deadline, "the run's lock was never released"
                    time.sleep(0.01)
                else:
                    break


# -- --stop-at-first-failure: the series ends there and its output is kept (#472) ------


def test_parse_args_reads_stop_at_first_failure_and_its_log(repeat: types.ModuleType) -> None:
    default = repeat.parse_args(["--", "tests/"])
    assert default.stop_at_first_failure is False
    named = repeat.parse_args(
        ["--stop-at-first-failure", "--failure-log", "first.log", "--", "tests/"]
    )
    assert named.stop_at_first_failure is True
    assert named.failure_log == Path("first.log")


def test_a_series_stops_after_its_first_failing_run(repeat: types.ModuleType) -> None:
    outcomes: list[tuple[int, frozenset[str]]] = [
        (0, frozenset()),
        (1, frozenset({"t"})),
        (0, frozenset()),
    ]

    def fake_run(_uv: str, _pytest_args: object) -> tuple[int, frozenset[str]]:
        return outcomes.pop(0)

    rules = repeat.SeriesRules(stop_at_first_failure=True)
    result = repeat.run_repeats("uv", ("tests/",), 3, run=fake_run, rules=rules)

    assert (result.passed, result.failed) == (1, 1)
    assert outcomes == [(0, frozenset())]  # the third run never started


def test_a_series_without_the_flag_goes_on_after_a_failing_run(repeat: types.ModuleType) -> None:
    outcomes: list[tuple[int, frozenset[str]]] = [(1, frozenset()), (0, frozenset())]

    def fake_run(_uv: str, _pytest_args: object) -> tuple[int, frozenset[str]]:
        return outcomes.pop(0)

    result = repeat.run_repeats("uv", ("tests/",), 2, run=fake_run)

    assert (result.passed, result.failed) == (1, 1)


def test_the_report_says_how_many_runs_ran_when_a_failure_stopped_the_series(
    repeat: types.ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    stopped = repeat.RepeatResult(
        times=20, passed=3, failed=1, failing_ids=frozenset({"t"}), stopped_by="first failure"
    )
    assert repeat.print_report(stopped, failure_log=Path("first.log")) == 1
    out = capsys.readouterr().out
    assert "4 of 20 run(s) ran, stopped at the first failure: 3 passed, 1 failed" in out
    assert "output of the failing run: first.log" in out


def _stand_in_uv(tmp_path: Path, *, exit_code: int) -> str:
    """A `uv` that prints a line on each stream and exits with `exit_code`."""
    stand_in = tmp_path / "uv"
    stand_in.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "print('to stdout')\n"
        "print('to stderr', file=sys.stderr)\n"
        f"sys.exit({exit_code})\n"
    )
    stand_in.chmod(0o755)
    return str(stand_in)


def test_a_failing_run_keeps_its_whole_output_in_the_named_file(
    repeat: types.ModuleType, tmp_path: Path
) -> None:
    log = tmp_path / "first.log"
    returncode, _ids = repeat.run_once(
        _stand_in_uv(tmp_path, exit_code=1), ("tests/",), failure_log=log
    )
    assert returncode == 1
    text = log.read_text()
    assert "to stdout" in text
    assert "to stderr" in text


def test_the_command_stops_at_the_first_failure_and_names_the_kept_output(
    repeat: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stand_in_uv(tmp_path, exit_code=1)
    log = tmp_path / "first.log"
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    argv = ["--times", "5", "--stop-at-first-failure", "--failure-log", str(log), "--", "tests/"]

    assert repeat.main(argv) == 1
    assert "to stdout" in log.read_text()
    assert "1 of 5 run(s) ran, stopped at the first failure" in capsys.readouterr().out


def test_a_passing_run_leaves_no_file(repeat: types.ModuleType, tmp_path: Path) -> None:
    log = tmp_path / "first.log"
    repeat.run_once(_stand_in_uv(tmp_path, exit_code=0), ("tests/",), failure_log=log)
    assert not log.exists()


# -- timestamped progress lines (#472) ----------------------------------------------


def test_each_progress_line_starts_with_the_time_the_run_ended_in_utc(
    repeat: types.ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    clock = [datetime(2026, 10, 24, 14, 0, 5, tzinfo=timezone(timedelta(hours=2)))]
    rules = repeat.SeriesRules(now=lambda: clock[0])
    outcomes: list[tuple[int, frozenset[str]]] = [(0, frozenset()), (1, frozenset({"t"}))]

    def fake_run(_uv: str, _pytest_args: object) -> tuple[int, frozenset[str]]:
        clock[0] += timedelta(minutes=3)
        return outcomes.pop(0)

    repeat.run_repeats("uv", ("tests/",), 2, run=fake_run, rules=rules)

    assert capsys.readouterr().out.splitlines() == [
        "[2026-10-24T12:03:05Z] run 1/2: exit code 0, 0 failing",
        "[2026-10-24T12:06:05Z] run 2/2: exit code 1, 1 failing",
    ]


# -- --deadline: no run starts after it (#472) --------------------------------------

_NOON = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def test_parse_args_reads_a_deadline_with_an_offset(repeat: types.ModuleType) -> None:
    assert repeat.parse_args(["--", "tests/"]).deadline is None
    args = repeat.parse_args(["--deadline", "2026-10-24T12:00:00Z", "--", "tests/"])
    assert args.deadline == _NOON
    offset = repeat.parse_args(["--deadline", "2026-10-24T14:00:00+02:00", "--", "tests/"])
    assert offset.deadline == _NOON


@pytest.mark.parametrize(
    ("text", "complaint"),
    [("2026-10-24T12:00:00", "UTC offset"), ("tomorrow", "not an ISO 8601 time")],
)
def test_parse_args_rejects_a_deadline_without_an_offset_or_not_a_time(
    repeat: types.ModuleType, capsys: pytest.CaptureFixture[str], text: str, complaint: str
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        repeat.parse_args(["--deadline", text, "--", "tests/"])
    assert exit_info.value.code == 2
    assert complaint in capsys.readouterr().err


def _ticking(
    clock: list[datetime], step: timedelta
) -> Callable[[str, object], tuple[int, frozenset[str]]]:
    """A fake run that takes `step` of the fake `clock` and passes."""

    def run(_uv: str, _pytest_args: object) -> tuple[int, frozenset[str]]:
        clock[0] += step
        return 0, frozenset[str]()

    return run


def test_no_run_starts_after_the_deadline(repeat: types.ModuleType) -> None:
    clock = [_NOON]
    rules = repeat.SeriesRules(deadline=_NOON + timedelta(minutes=25), now=lambda: clock[0])

    result = repeat.run_repeats(
        "uv", ("t",), 10, run=_ticking(clock, timedelta(minutes=10)), rules=rules
    )

    assert (result.passed, result.failed) == (3, 0)  # starts at 0, 10 and 20 minutes
    assert result.stopped_by == "deadline"


def test_a_run_that_starts_at_the_deadline_is_too_late(repeat: types.ModuleType) -> None:
    clock = [_NOON]
    rules = repeat.SeriesRules(deadline=_NOON + timedelta(minutes=20), now=lambda: clock[0])

    result = repeat.run_repeats(
        "uv", ("t",), 10, run=_ticking(clock, timedelta(minutes=10)), rules=rules
    )

    assert result.passed == 2


def test_a_deadline_already_past_runs_nothing(repeat: types.ModuleType) -> None:
    clock = [_NOON]
    rules = repeat.SeriesRules(deadline=_NOON - timedelta(seconds=1), now=lambda: clock[0])

    result = repeat.run_repeats(
        "uv", ("t",), 3, run=_ticking(clock, timedelta(minutes=1)), rules=rules
    )

    assert (result.passed, result.failed) == (0, 0)
    assert result.stopped_by == "deadline"


def test_a_series_that_finishes_before_its_deadline_is_not_stopped(
    repeat: types.ModuleType,
) -> None:
    clock = [_NOON]
    rules = repeat.SeriesRules(deadline=_NOON + timedelta(hours=1), now=lambda: clock[0])

    result = repeat.run_repeats(
        "uv", ("t",), 3, run=_ticking(clock, timedelta(minutes=1)), rules=rules
    )

    assert (result.passed, result.stopped_by) == (3, "")


def test_a_run_that_waited_for_the_lock_past_the_deadline_does_not_start(
    repeat: types.ModuleType,
) -> None:
    clock = [_NOON]
    events: list[str] = []
    rules = repeat.SeriesRules(deadline=_NOON + timedelta(minutes=1), now=lambda: clock[0])

    @contextlib.contextmanager
    def hold() -> Iterator[int | None]:
        clock[0] += timedelta(minutes=5)  # the wait for the lock
        events.append("lock in")
        try:
            yield None
        finally:
            events.append("lock out")

    locked = repeat.locked_run(
        _run_recording(events), hold=hold, load=_recorded(events, "load"), rules=rules
    )
    result = repeat.run_repeats("uv", ("t",), 3, run=locked, rules=rules)

    assert (result.passed, result.failed, result.stopped_by) == (0, 0, "deadline")
    assert events == ["lock in", "lock out"]


def test_the_report_says_how_many_runs_ran_before_the_deadline(
    repeat: types.ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    cut = repeat.RepeatResult(
        times=20, passed=7, failed=0, failing_ids=frozenset(), stopped_by="deadline"
    )
    assert repeat.print_report(cut) == 3  # not 0: fewer runs than asked passed
    assert "7 of 20 run(s) ran, stopped at the deadline: 7 passed, 0 failed" in (
        capsys.readouterr().out
    )


def test_the_command_runs_nothing_after_a_deadline_that_has_passed(
    repeat: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stand_in_uv(tmp_path, exit_code=0)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    argv = ["--times", "5", "--deadline", "2020-01-01T00:00:00Z", "--", "tests/"]

    assert repeat.main(argv) == 3
    assert "0 of 5 run(s) ran, stopped at the deadline" in capsys.readouterr().out
