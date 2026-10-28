"""scripts/wait_for.py: waits for a file or a log line, against a temp file."""

import importlib.util
import threading
import time
import types
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "wait_for.py"


@pytest.fixture(scope="module")
def wait_for() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("wait_for", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_later(path: Path, text: str, delay: float) -> threading.Thread:
    def write() -> None:
        time.sleep(delay)
        path.write_text(text)

    thread = threading.Thread(target=write)
    thread.start()
    return thread


def test_a_file_that_exists_is_found_at_once_and_its_first_line_printed(
    wait_for: types.ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc_file = tmp_path / "run.rc"
    rc_file.write_text("0\nsecond line\n")
    assert wait_for.main([str(rc_file), "--timeout", "5"]) == 0
    assert capsys.readouterr().out == f"found {rc_file}: 0\n"


def test_an_empty_file_is_found_too(
    wait_for: types.ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc_file = tmp_path / "run.rc"
    rc_file.write_text("")
    assert wait_for.main([str(rc_file), "--timeout", "5"]) == 0
    assert capsys.readouterr().out == f"found {rc_file}\n"


def test_a_file_written_while_it_waits_is_found(
    wait_for: types.ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc_file = tmp_path / "run.rc"
    writer = _write_later(rc_file, "7\n", delay=0.3)
    try:
        assert wait_for.main([str(rc_file), "--timeout", "10"]) == 0
    finally:
        writer.join()
    assert capsys.readouterr().out == f"found {rc_file}: 7\n"


def test_a_missing_file_times_out_with_rc_1_and_says_what_it_waited_for(
    wait_for: types.ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "never.rc"
    assert wait_for.main([str(missing), "--timeout", "0.3"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"timed out after 0.3 s waiting for {missing}\n"


def test_a_pattern_prints_the_first_matching_line_with_its_number(
    wait_for: types.ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = tmp_path / "run.log"
    log.write_text("starting\nDone (3.1s)! For help\nDone (9.9s)!\n")
    assert wait_for.main([str(log), "--pattern", r"Done \(", "--timeout", "5"]) == 0
    assert capsys.readouterr().out == f"{log}:2:Done (3.1s)! For help\n"


def test_a_file_without_the_pattern_is_not_found_yet(
    wait_for: types.ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = tmp_path / "run.log"
    log.write_text("starting\n")
    assert wait_for.main([str(log), "--pattern", "Done", "--timeout", "0.3"]) == 1
    assert capsys.readouterr().err == f"timed out after 0.3 s waiting for {log} to match 'Done'\n"


def test_a_pattern_that_appears_later_in_the_log_is_found(
    wait_for: types.ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = tmp_path / "run.log"
    log.write_text("starting\n")
    writer = _write_later(log, "starting\nDone\n", delay=0.3)
    try:
        assert wait_for.main([str(log), "--pattern", "Done", "--timeout", "10"]) == 0
    finally:
        writer.join()
    assert capsys.readouterr().out == f"{log}:2:Done\n"


def test_a_log_with_bytes_that_are_not_utf8_is_still_searched(
    wait_for: types.ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = tmp_path / "run.log"
    log.write_bytes(b"\xff\xfe garbage\nDone\n")
    assert wait_for.main([str(log), "--pattern", "Done", "--timeout", "5"]) == 0
    assert capsys.readouterr().out == f"{log}:2:Done\n"


def test_an_invalid_pattern_is_a_usage_error(wait_for: types.ModuleType, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exit_info:
        wait_for.main([str(tmp_path / "x.log"), "--pattern", "("])
    assert exit_info.value.code == 2


def test_the_default_timeout_stays_under_the_bash_tools_ten_minutes(
    wait_for: types.ModuleType,
) -> None:
    assert 0 < wait_for.DEFAULT_TIMEOUT < 600


def test_wait_polls_until_the_check_finds_something(wait_for: types.ModuleType) -> None:
    clock = [0.0]
    answers = iter([None, None, "ready"])

    def sleep(seconds: float) -> None:
        clock[0] += seconds

    found = wait_for.wait(
        lambda: next(answers), timeout=10, interval=1, now=lambda: clock[0], sleep=sleep
    )
    assert found == "ready"
    assert clock[0] == 2


def test_wait_gives_up_once_the_timeout_has_passed(wait_for: types.ModuleType) -> None:
    clock = [0.0]

    def sleep(seconds: float) -> None:
        clock[0] += seconds

    found = wait_for.wait(lambda: None, timeout=3, interval=1, now=lambda: clock[0], sleep=sleep)
    assert found is None
    assert clock[0] == 3
