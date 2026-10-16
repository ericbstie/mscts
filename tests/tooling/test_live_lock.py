"""Live tiers wait for the shared lock, pass exit codes through and allow a bypass (#138)."""

import fcntl
import importlib.util
import os
import select
import signal
import subprocess
import sys
import time
import tomllib
import types
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import IO

import pytest
from support.leak_guard import kill_survivors

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "live_lock.py"
HELD_VARIABLE = "MSCTS_LIVE_LOCK_HELD"
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
    tmp_path: Path,
    exit_code: int = 0,
    *,
    bypass: bool = False,
    inside_holder: bool = False,
    child: str = CHILD,
) -> Iterator[subprocess.Popen[str]]:
    """Start the wrapper on `child`, as a process of its own.

    `inside_holder` runs it as a command of another holder would, with the variable that
    holder exports. Otherwise it is an unrelated process, whatever this test run inherits.
    """
    tag = f"MSCTS_LIVE_LOCK_TEST={uuid.uuid4().hex}"
    env = {key: value for key, value in os.environ.items() if key != HELD_VARIABLE}
    env |= {
        "MSCTS_CACHE": str(tmp_path / "cache"),
        "MSCTS_LIVE_LOCK": "0" if bypass else "1",
        "MSCTS_LIVE_LOCK_TEST": tag.partition("=")[2],
        "MSCTS_LIVE_LOCK_TEST_PID": str(tmp_path / "child.pid"),
    }
    if inside_holder:
        env[HELD_VARIABLE] = "1"
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


def until_the_wrapper_names_its_command(tmp_path: Path, wrapper: subprocess.Popen[str]) -> int:
    """Wait until the lock file names a pid other than the wrapper's own, and return it.

    The wrapper writes its own pid, starts the command, then writes the command's pid. The
    command can print `started` before that second write (#171), so `started` alone does not
    say which pid a waiter will name.
    """
    lock = tmp_path / "cache" / "live-tier.lock"
    deadline = time.monotonic() + 5
    while not (named := lock.read_text().strip()).isdigit() or named == str(wrapper.pid):
        assert wrapper.poll() is None, "the wrapper exited before naming its command"
        assert time.monotonic() < deadline, f"the lock file still names {named or 'nobody'}"
        time.sleep(0.01)
    return int(named)


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
        holder = until_the_wrapper_names_its_command(tmp_path, first)
        assert holder == int((tmp_path / "child.pid").read_text())
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


@contextmanager
def frozen_waiter(tmp_path: Path, holder: subprocess.Popen[str]) -> Iterator[subprocess.Popen[str]]:
    """Queue a waiter behind `holder`, freeze it, and let `holder` finish: the lock is free.

    A frozen waiter cannot take the lock, so a newcomer that is not queued behind it can
    take it first every time (a woken waiter and a fresh process otherwise race, #374).
    """
    with command(tmp_path) as waiter:
        assert line(waiter.stderr).startswith("waiting for another live tier to finish")
        os.kill(waiter.pid, signal.SIGSTOP)
        _, status = os.waitpid(waiter.pid, os.WUNTRACED)
        assert os.WIFSTOPPED(status)
        assert finish(holder) == 0
        yield waiter


def test_a_newcomer_waits_behind_a_waiter_that_queued_first(tmp_path: Path) -> None:
    with command(tmp_path) as holder:
        assert line(holder.stdout) == "started"
        until_the_wrapper_names_its_command(tmp_path, holder)
        with frozen_waiter(tmp_path, holder) as first, command(tmp_path) as late:
            assert late.stdout is not None
            assert late.stderr is not None
            ready, _, _ = select.select([late.stdout, late.stderr], [], [], 5)
            assert late.stdout not in ready, "a newcomer took the lock ahead of a queued waiter"
            assert line(late.stderr).startswith("waiting for another live tier to finish")
            os.kill(first.pid, signal.SIGCONT)
            assert line(first.stdout) == "started"
            assert finish(first) == 0
            assert line(late.stdout) == "started"
            assert finish(late) == 0


def test_waiters_run_in_the_order_they_asked(tmp_path: Path) -> None:
    with command(tmp_path) as holder:
        assert line(holder.stdout) == "started"
        until_the_wrapper_names_its_command(tmp_path, holder)
        with command(tmp_path) as first:
            assert line(first.stderr).startswith("waiting for another live tier to finish")
            with command(tmp_path) as second:
                assert line(second.stderr).startswith("waiting for another live tier to finish")
                assert finish(holder) == 0
                assert line(first.stdout) == "started"
                assert second.stdout is not None
                assert not select.select([second.stdout], [], [], 0.3)[0]
                assert finish(first) == 0
                assert line(second.stdout) == "started"
                assert finish(second) == 0


def test_a_waiter_that_dies_in_the_queue_holds_no_one_up(tmp_path: Path) -> None:
    with command(tmp_path) as holder:
        assert line(holder.stdout) == "started"
        until_the_wrapper_names_its_command(tmp_path, holder)
        with frozen_waiter(tmp_path, holder) as dead, command(tmp_path) as next_in_line:
            assert line(next_in_line.stderr).startswith("waiting for another live tier to finish")
            dead.kill()
            assert dead.wait(timeout=5) == -signal.SIGKILL
            assert line(next_in_line.stdout) == "started"
            assert finish(next_in_line) == 0


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
        holder = until_the_wrapper_names_its_command(tmp_path, first)
        assert holder == int((tmp_path / "child.pid").read_text())
        with command(tmp_path, bypass=True) as second:
            assert line(second.stdout) == "started"
            assert first.poll() is None
            assert (tmp_path / "cache" / "live-tier.lock").read_text().strip() == str(holder)
            assert finish(second) == 0
            assert second.stderr is not None
            assert second.stderr.read() == ""
        assert finish(first) == 0


def test_the_holders_command_is_told_who_holds_the_lock(tmp_path: Path) -> None:
    child = f"import os\nprint('held by', os.environ.get({HELD_VARIABLE!r}), flush=True)\n"
    with command(tmp_path, child=child) as holder:
        assert line(holder.stdout) == f"held by {holder.pid}"
        assert finish(holder) == 0


def test_a_command_inside_a_holders_command_runs_without_waiting(tmp_path: Path) -> None:
    with command(tmp_path) as holder:
        assert line(holder.stdout) == "started"
        named = until_the_wrapper_names_its_command(tmp_path, holder)
        with command(tmp_path, inside_holder=True) as nested:
            assert line(nested.stdout) == "started"
            assert (tmp_path / "cache" / "live-tier.lock").read_text().strip() == str(named)
            assert finish(nested) == 0
            assert nested.stderr is not None
            assert nested.stderr.read() == ""
        assert finish(holder) == 0


def test_a_live_tier_run_by_a_holders_command_does_not_wait_for_its_holder(
    tmp_path: Path,
) -> None:
    inner = [sys.executable, str(SCRIPT), "--", sys.executable, "-I", "-S", "-c", "print('inner')"]
    child = f"import subprocess\nsubprocess.run({inner!r}, timeout=5, check=True)\nprint('done')\n"
    with command(tmp_path, child=child) as holder:
        assert line(holder.stdout) == "inner"
        assert line(holder.stdout) == "done"
        assert finish(holder) == 0


def test_a_hold_marks_its_environment_for_the_block(tmp_path: Path) -> None:
    live_lock = load_live_lock()
    environ: dict[str, str] = {}
    with live_lock.hold_live_lock(tmp_path, environ):
        assert environ == {HELD_VARIABLE: str(os.getpid())}
    assert environ == {}


def test_a_hold_inside_a_holders_command_takes_nothing(tmp_path: Path) -> None:
    live_lock = load_live_lock()
    environ = {HELD_VARIABLE: "1"}
    with live_lock.hold_live_lock(tmp_path, environ) as descriptor:
        assert descriptor is None
        assert not (tmp_path / "live-tier.lock").exists()
    assert environ == {HELD_VARIABLE: "1"}


def test_a_bypassed_hold_takes_nothing(tmp_path: Path) -> None:
    live_lock = load_live_lock()
    environ = {"MSCTS_LIVE_LOCK": "0"}
    with live_lock.hold_live_lock(tmp_path, environ) as descriptor:
        assert descriptor is None
        assert not (tmp_path / "live-tier.lock").exists()
    assert environ == {"MSCTS_LIVE_LOCK": "0"}


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
        holder = until_the_wrapper_names_its_command(tmp_path, first)
        assert holder == int((tmp_path / "child.pid").read_text())
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
wanted = {signal.SIGINT, signal.SIGTERM}
for number in wanted:
    signal.signal(number, signal.SIG_DFL)
signal.pthread_sigmask(signal.SIG_BLOCK, wanted)
os.write(1, b'started\n')
received = signal.sigwait(wanted)
os.write(1, f'stopping {int(received)}\n'.encode())
sys.stdin.read()
sys.exit(23)
"""
    with command(tmp_path, child=child) as first:
        assert line(first.stdout) == "started"
        holder = until_the_wrapper_names_its_command(tmp_path, first)
        if to_group:
            os.killpg(first.pid, termination)
        else:
            first.send_signal(termination)
        stopped = line(first.stdout)
        assert first.stderr is not None
        assert stopped == f"stopping {int(termination)}", first.stderr.read()
        with command(tmp_path) as second:
            assert line(second.stderr) == f"waiting for another live tier to finish (pid {holder})"
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


def test_a_finished_holder_leaves_no_pid_for_a_waiter_to_name(tmp_path: Path) -> None:
    with command(tmp_path) as process:
        assert line(process.stdout) == "started"
        assert finish(process) == 0
    assert (tmp_path / "cache" / "live-tier.lock").read_text() == ""


def load_live_lock() -> types.ModuleType:
    """Load scripts/live_lock.py by path (scripts/ is not an importable package)."""
    spec = importlib.util.spec_from_file_location("live_lock", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_hold_keeps_the_lock_until_its_block_ends(tmp_path: Path) -> None:
    live_lock = load_live_lock()
    lock = tmp_path / "live-tier.lock"
    with live_lock.hold_live_lock(tmp_path, {}) as descriptor:
        assert isinstance(descriptor, int)
        assert lock.read_text().strip() == str(os.getpid())
        with lock.open("r+") as other, pytest.raises(BlockingIOError):
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert lock.read_text() == ""
    with lock.open("r+") as other:
        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_a_signal_that_arrives_before_the_command_starts_reaches_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # #211: the wrapper keeps such a signal and forwards it once the command has started.
    # Only the moment between its handlers going in and the command starting has no
    # command yet, so the signal arrives there, from inside the wrapper itself.
    live_lock = load_live_lock()
    real_popen = subprocess.Popen

    def signalled_first(
        args: list[str], *, start_new_session: bool, pass_fds: Sequence[int]
    ) -> subprocess.Popen[bytes]:
        signal.raise_signal(signal.SIGTERM)
        return real_popen(args, start_new_session=start_new_session, pass_fds=pass_fds)

    monkeypatch.setattr(live_lock.subprocess, "Popen", signalled_first)
    # Without the signal, the command ends by itself, so a dropped one fails, not hangs.
    sleeper = [sys.executable, "-I", "-S", "-c", "import time; time.sleep(5)"]

    assert live_lock._run_command(sleeper) == -signal.SIGTERM  # noqa: SLF001


def test_an_interrupt_reaches_a_grandchild_behind_a_parent_that_ignores_it(
    tmp_path: Path,
) -> None:
    """`uv run pytest` is this shape: uv ignores Ctrl-C and waits, pytest must still get it."""
    child = r"""
import signal, subprocess, sys
signal.signal(signal.SIGINT, signal.SIG_IGN)
grandchild = (
    "import os, signal\n"
    "signal.signal(signal.SIGINT, signal.SIG_DFL)\n"
    "signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})\n"
    "os.write(1, b'started\\n')\n"
    "received = signal.sigwait({signal.SIGINT})\n"
    "os.write(1, f'interrupted {int(received)}\\n'.encode())\n"
)
subprocess.run([sys.executable, "-I", "-S", "-c", grandchild])
sys.exit(23)
"""
    with command(tmp_path, child=child) as process:
        assert line(process.stdout) == "started"
        process.send_signal(signal.SIGINT)
        assert line(process.stdout) == f"interrupted {int(signal.SIGINT)}"
        assert process.wait(timeout=5) == 23


@pytest.mark.parametrize("tier", ["reference", "selfcheck", "candidate"])
def test_each_live_tier_task_names_its_tier_to_the_lock_wrapper(tier: str) -> None:
    mise_toml = tomllib.loads((SCRIPT.parents[1] / "mise.toml").read_text(encoding="utf-8"))
    assert f"scripts/live_lock.py --tier {tier} --" in mise_toml["tasks"][f"test:{tier}"]["run"]


@pytest.mark.parametrize(
    ("tier", "adapter"),
    [("candidate", "pumpkin"), ("reference", "vanilla"), ("selfcheck", "vanilla")],
)
def test_a_tier_without_its_installation_fails_before_it_waits_for_the_lock(
    tmp_path: Path, tier: str, adapter: str
) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    with (cache / "live-tier.lock").open("w") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX)
        process = subprocess.Popen(
            [sys.executable, str(SCRIPT), "--tier", tier, "--", sys.executable, "-c", ""],
            env={**os.environ, "MSCTS_CACHE": str(cache), "MSCTS_LIVE_LOCK": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            code = process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            msg = f"the {tier} run waited for the lock before it checked for {adapter}"
            raise AssertionError(msg) from None
    _, err = process.communicate()
    assert code == 1
    assert f"mscts adapter install {adapter}" in err
