"""support.leak_guard: tagging a process's environment and sweeping /proc for survivors."""

import os
import subprocess
import sys
import uuid
from pathlib import Path

from support import leak_guard


def _write_environ(proc_dir: Path, pid: int, entries: list[str]) -> None:
    (proc_dir / str(pid)).mkdir()
    (proc_dir / str(pid) / "environ").write_bytes(b"\0".join(e.encode() for e in entries) + b"\0")


def test_tagged_pids_finds_only_processes_holding_the_exact_token(tmp_path: Path) -> None:
    proc_dir = tmp_path / "proc"
    proc_dir.mkdir()
    _write_environ(proc_dir, 10, ["PATH=/bin", "MSCTS_TOKEN=abc"])
    _write_environ(proc_dir, 11, ["MSCTS_TOKEN=xyz"])  # a different token
    _write_environ(proc_dir, 12, ["PATH=/bin"])  # no token at all
    (proc_dir / "self").mkdir()  # not a pid

    assert leak_guard.tagged_pids("MSCTS_TOKEN=abc", proc_dir=proc_dir) == [10]


def test_tagged_pids_skips_a_process_that_has_already_gone(tmp_path: Path) -> None:
    proc_dir = tmp_path / "proc"
    proc_dir.mkdir()
    (proc_dir / "13").mkdir()  # no environ file: gone, or unreadable

    assert leak_guard.tagged_pids("MSCTS_TOKEN=abc", proc_dir=proc_dir) == []


def test_kill_survivors_returns_nothing_when_nothing_is_tagged(tmp_path: Path) -> None:
    proc_dir = tmp_path / "proc"
    proc_dir.mkdir()

    assert leak_guard.kill_survivors("MSCTS_TOKEN=abc", within=0.05, proc_dir=proc_dir) == []


def test_kill_survivors_kills_and_reports_a_real_tagged_process() -> None:
    token = f"MSCTS_LEAK_GUARD_TEST={uuid.uuid4().hex}"
    name, _, value = token.partition("=")
    helper = subprocess.Popen(
        [sys.executable, "-I", "-S", "-c", "import sys; sys.stdin.read()"],
        stdin=subprocess.PIPE,
        env={**os.environ, name: value},
    )
    try:
        leaked = leak_guard.kill_survivors(token, within=1.0)
        assert leaked == [helper.pid]
        helper.wait(timeout=5)  # already killed; this just reaps it
        assert helper.returncode is not None
    finally:
        if helper.poll() is None:
            helper.kill()
            helper.wait(timeout=5)
        assert helper.stdin is not None
        helper.stdin.close()


def test_kill_survivors_does_not_kill_a_process_that_stops_in_time() -> None:
    token = f"MSCTS_LEAK_GUARD_TEST={uuid.uuid4().hex}"
    name, _, value = token.partition("=")
    helper = subprocess.Popen(
        [sys.executable, "-I", "-S", "-c", "import sys; sys.stdin.read()"],
        stdin=subprocess.PIPE,
        env={**os.environ, name: value},
    )
    assert helper.stdin is not None
    helper.stdin.close()  # ends the helper right away, well within the guard's window
    helper.wait(timeout=5)

    leaked = leak_guard.kill_survivors(token, within=1.0)

    assert leaked == []
