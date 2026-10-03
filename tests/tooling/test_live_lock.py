"""Live tiers wait for the shared lock, pass exit codes through and allow a bypass (#138)."""

import fcntl
import os
import select
import signal
import subprocess
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO

import pytest
from support.leak_guard import kill_survivors

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "live_lock.py"
CHILD = """
import os, sys
from pathlib import Path
Path(os.environ['MSCTS_LIVE_LOCK_TEST_PID']).write_text(str(os.getpid()))
print('started', flush=True)
sys.stdin.read()
sys.exit(int(sys.argv[1]))
"""


@contextmanager
def command(
    tmp_path: Path, exit_code: int = 0, *, bypass: bool = False, child: str = CHILD
) -> Iterator[subprocess.Popen[str]]:
    tag = f"MSCTS_LIVE_LOCK_TEST={uuid.uuid4().hex}"
    env = {
        **os.environ,
        "MSCTS_CACHE": str(tmp_path / "cache"),
        "MSCTS_LIVE_LOCK": "0" if bypass else "1",
        "MSCTS_LIVE_LOCK_TEST": tag.partition("=")[2],
        "MSCTS_LIVE_LOCK_TEST_PID": str(tmp_path / "child.pid"),
    }
    process = subprocess.Popen(
        [
            sys.executable,
            str(SCRIPT),
            "--",
            sys.executable,
            "-I",
            "-S",
            "-c",
            child,
            str(exit_code),
        ],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        yield process
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            assert stream is not None
            stream.close()
        if Path("/proc").is_dir():
            assert kill_survivors(tag) == []


def line(stream: IO[str] | None) -> str:
    assert stream is not None
    ready, _, _ = select.select([stream], [], [], 5)
    assert ready, "the command produced no expected output"
    return stream.readline().strip()


def finish(process: subprocess.Popen[str]) -> int:
    assert process.stdin is not None
    process.stdin.close()
    return process.wait(timeout=5)


@pytest.mark.parametrize("prefix", ["", "import os; os.closerange(3, 256)\n"])
def test_a_second_live_tier_waits_then_runs_when_the_holder_exits(
    tmp_path: Path, prefix: str
) -> None:
    with command(tmp_path, child=prefix + CHILD) as first:
        assert line(first.stdout) == "started"
        holder = int((tmp_path / "child.pid").read_text())
        with command(tmp_path) as second:
            assert second.stdout is not None
            assert second.stderr is not None
            ready, _, _ = select.select([second.stdout, second.stderr], [], [], 5)
            assert second.stdout not in ready, (
                "the second command ran before the holder released the lock"
            )
            assert second.stderr in ready
            assert line(second.stderr) == f"waiting for another live tier to finish (pid {holder})"
            assert (tmp_path / "cache" / "live-tier.lock").read_text().strip() == str(holder)
            assert finish(first) == 0
            assert line(second.stdout) == "started"
            assert finish(second) == 0
            assert second.stderr.read() == ""


@pytest.mark.parametrize("exit_code", [0, 7])
def test_the_command_exit_code_passes_through(tmp_path: Path, exit_code: int) -> None:
    with command(tmp_path, exit_code) as process:
        assert line(process.stdout) == "started"
        assert finish(process) == exit_code


@pytest.mark.parametrize("termination", [signal.SIGTERM, signal.SIGKILL])
def test_the_commands_terminating_signal_passes_through(tmp_path: Path, termination: int) -> None:
    child = CHILD.replace(
        "sys.exit(int(sys.argv[1]))", "import os; os.kill(os.getpid(), int(sys.argv[1]))"
    )
    with command(tmp_path, termination, child=child) as process:
        assert line(process.stdout) == "started"
        assert finish(process) == -termination


def test_the_bypass_runs_while_another_live_tier_holds_the_lock(tmp_path: Path) -> None:
    with command(tmp_path) as first:
        assert line(first.stdout) == "started"
        holder = (tmp_path / "child.pid").read_text()
        with command(tmp_path, bypass=True) as second:
            assert line(second.stdout) == "started"
            assert first.poll() is None
            assert (tmp_path / "cache" / "live-tier.lock").read_text().strip() == holder
            assert finish(second) == 0
            assert second.stderr is not None
            assert second.stderr.read() == ""
        assert finish(first) == 0


def test_a_descendant_does_not_keep_the_lock_after_the_command_exits(tmp_path: Path) -> None:
    child = f"""
import subprocess, sys
subprocess.Popen([sys.executable, '-I', '-S', '-c', {CHILD!r}, '0'], close_fds=False)
"""
    with command(tmp_path, child=child) as first:
        assert line(first.stdout) == "started"
        assert first.wait(timeout=5) == 0
        with command(tmp_path) as second:
            assert line(second.stdout) == "started"
            assert finish(second) == 0
        assert finish(first) == 0


def test_killing_the_wrapper_keeps_the_lock_until_its_command_exits(tmp_path: Path) -> None:
    with command(tmp_path) as first:
        assert line(first.stdout) == "started"
        holder = int((tmp_path / "child.pid").read_text())
        first.kill()
        assert first.wait(timeout=5) == -signal.SIGKILL
        with (
            (tmp_path / "cache" / "live-tier.lock").open("r+") as lock,
            pytest.raises(BlockingIOError),
        ):
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with command(tmp_path) as second:
            assert line(second.stderr) == f"waiting for another live tier to finish (pid {holder})"
            assert first.stdin is not None
            first.stdin.close()
            assert line(second.stdout) == "started"
            assert finish(second) == 0


@pytest.mark.parametrize("termination", [signal.SIGINT, signal.SIGTERM])
@pytest.mark.parametrize("to_group", [False, True])
def test_signals_reach_the_command_before_the_lock_is_released(
    tmp_path: Path, termination: int, *, to_group: bool
) -> None:
    child = r"""
import os, signal, sys
def stop(number, frame):
    os.write(1, b'stopping\n')
    sys.stdin.read()
    sys.exit(23)
signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)
os.write(1, b'started\n')
while True:
    signal.pause()
"""
    with command(tmp_path, child=child) as first:
        assert line(first.stdout) == "started"
        if to_group:
            os.killpg(first.pid, termination)
        else:
            first.send_signal(termination)
        stopped = line(first.stdout)
        assert first.stderr is not None
        assert stopped == "stopping", first.stderr.read()
        with command(tmp_path) as second:
            assert line(second.stderr).startswith("waiting for another live tier to finish (pid ")
            assert finish(first) == 23
            assert line(second.stdout) == "started"
            assert finish(second) == 0


def test_a_terminal_signal_waits_for_the_wrapper_to_forward_it(tmp_path: Path) -> None:
    child = r"""
import os, signal, sys
received = 0
def stop(number, frame):
    global received
    received += 1
    os.write(1, f'signal {received}\n'.encode())
signal.signal(signal.SIGTERM, stop)
os.write(1, b'started\n')
while os.read(0, 1):
    os.write(1, f'received {received}\n'.encode())
sys.exit(23)
"""
    with command(tmp_path, child=child) as process:
        assert line(process.stdout) == "started"
        os.kill(process.pid, signal.SIGSTOP)
        _, status = os.waitpid(process.pid, os.WUNTRACED)
        assert os.WIFSTOPPED(status)
        try:
            os.killpg(process.pid, signal.SIGTERM)
            assert process.stdin is not None
            process.stdin.write("?")
            process.stdin.flush()
            assert line(process.stdout) == "received 0"
        finally:
            os.kill(process.pid, signal.SIGCONT)
        assert line(process.stdout) == "signal 1"
        assert finish(process) == 23
