"""scripts/strays.py's pure and /proc-reading parts, hermetic (a synthetic /proc tree)."""

import contextlib
import importlib.util
import re
import subprocess
import sys
import types
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

_STRAYS_PATH = Path(__file__).resolve().parents[2] / "scripts" / "strays.py"


def _load_strays() -> types.ModuleType:
    """Load scripts/strays.py by path (scripts/ is not an importable package)."""
    spec = importlib.util.spec_from_file_location("strays", _STRAYS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def strays() -> types.ModuleType:
    return _load_strays()


def _write_proc_entry(proc_dir: Path, pid: int, *, argv: list[str], ppid: int, comm: str) -> None:
    """A synthetic /proc/<pid>/{cmdline,stat}, in the kernel's exact formats."""
    entry = proc_dir / str(pid)
    entry.mkdir()
    (entry / "cmdline").write_bytes(b"\0".join(part.encode() for part in argv) + b"\0")
    # "pid (comm) state ppid pgrp session tty_nr tpgid flags ...": only state and ppid matter
    # here, but a comm holding a space or ")" is exactly why ppid is parsed after the last ")".
    (entry / "stat").write_text(f"{pid} ({comm}) S {ppid} {pid} {pid} 0 -1 0\n")


@pytest.fixture
def proc_dir(tmp_path: Path) -> Path:
    return tmp_path / "proc"


# -- all_pids / read_cmdline / read_ppid (synthetic /proc) -------------------------


def test_all_pids_lists_only_numeric_entries(strays: types.ModuleType, proc_dir: Path) -> None:
    proc_dir.mkdir()
    _write_proc_entry(proc_dir, 1, argv=["init"], ppid=0, comm="init")
    _write_proc_entry(proc_dir, 42, argv=["sleep", "1"], ppid=1, comm="sleep")
    (proc_dir / "self").mkdir()  # not a pid
    (proc_dir / "sys").mkdir()  # not a pid

    assert strays.all_pids(proc_dir) == [1, 42]


def test_read_cmdline_returns_the_argv(strays: types.ModuleType, proc_dir: Path) -> None:
    proc_dir.mkdir()
    _write_proc_entry(proc_dir, 7, argv=["java", "-jar", "server.jar"], ppid=1, comm="java")

    assert strays.read_cmdline(7, proc_dir) == ["java", "-jar", "server.jar"]


def test_read_cmdline_returns_none_for_a_gone_process(
    strays: types.ModuleType, proc_dir: Path
) -> None:
    proc_dir.mkdir()
    assert strays.read_cmdline(99999, proc_dir) is None


def test_read_ppid_returns_the_parent_pid(strays: types.ModuleType, proc_dir: Path) -> None:
    proc_dir.mkdir()
    _write_proc_entry(proc_dir, 7, argv=["x"], ppid=3, comm="x")

    assert strays.read_ppid(7, proc_dir) == 3


def test_read_ppid_handles_a_comm_with_a_space_and_a_close_paren(
    strays: types.ModuleType, proc_dir: Path
) -> None:
    proc_dir.mkdir()
    _write_proc_entry(proc_dir, 7, argv=["x"], ppid=3, comm="weird (name) )")

    assert strays.read_ppid(7, proc_dir) == 3


def test_read_ppid_returns_none_for_a_gone_process(
    strays: types.ModuleType, proc_dir: Path
) -> None:
    proc_dir.mkdir()
    assert strays.read_ppid(99999, proc_dir) is None


# -- ancestors -----------------------------------------------------------------------


def test_ancestors_walks_up_to_and_including_pid_1(strays: types.ModuleType) -> None:
    ppids = {100: 50, 50: 10, 10: 1, 1: 0}

    assert strays.ancestors(100, ppid_of=ppids.get) == {50, 10, 1}


def test_ancestors_of_pid_1_is_empty(strays: types.ModuleType) -> None:
    assert strays.ancestors(1, ppid_of={1: 0}.get) == set()


def test_ancestors_stops_on_an_unreadable_parent(strays: types.ModuleType) -> None:
    ppids = {100: 50}  # 50's ppid cannot be read (the process is gone)

    assert strays.ancestors(100, ppid_of=ppids.get) == {50}


def test_ancestors_does_not_loop_forever_on_a_cycle(strays: types.ModuleType) -> None:
    # Should never happen on a real kernel, but a bug here must not hang the tool.
    ppids = {1: 2, 2: 1}

    assert strays.ancestors(1, ppid_of=ppids.get) == {2}


# -- find_strays ----------------------------------------------------------------------


def test_find_strays_matches_the_joined_argv(strays: types.ModuleType) -> None:
    cmdlines = {10: ["java", "-jar", "server.jar"], 11: ["sleep", "1"]}

    found = strays.find_strays(
        [10, 11], re.compile("server.jar"), exclude=set(), cmdline_of=cmdlines.get
    )

    assert found == [(10, ["java", "-jar", "server.jar"])]


def test_find_strays_excludes_the_given_pids(strays: types.ModuleType) -> None:
    cmdlines = {10: ["java", "-jar", "server.jar"]}

    found = strays.find_strays(
        [10], re.compile("server.jar"), exclude={10}, cmdline_of=cmdlines.get
    )

    assert found == []


def test_find_strays_skips_a_pid_that_has_already_gone(strays: types.ModuleType) -> None:
    cmdlines: dict[int, list[str] | None] = {10: None}

    found = strays.find_strays([10], re.compile("."), exclude=set(), cmdline_of=cmdlines.get)

    assert found == []


def test_find_strays_is_a_regex_not_a_plain_substring(strays: types.ModuleType) -> None:
    cmdlines = {10: ["java", "-jar", "vanilla-26.3.jar"]}

    found = strays.find_strays(
        [10], re.compile(r"vanilla-26\.3\.jar$"), exclude=set(), cmdline_of=cmdlines.get
    )

    assert found == [(10, ["java", "-jar", "vanilla-26.3.jar"])]


# -- main, against a real /proc, never matches its own harness's shell wrapper -----

_HELPER = "import sys; print(flush=True); sys.stdin.read()"
"""A helper that says it is running (its argv is then final), and waits for stdin to close."""


@contextlib.contextmanager
def running_helper(argv: list[str]) -> Iterator[subprocess.Popen[bytes]]:
    """Run `argv` for the body, entered once it runs: until its exec, /proc shows pytest's argv.

    On exit it closes the helper's stdin (so it ends), waits for it, and closes its stdout.
    """
    helper = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    assert helper.stdin is not None
    assert helper.stdout is not None
    try:
        helper.stdout.readline()
        yield helper
    finally:
        helper.stdin.close()
        helper.wait(timeout=5)
        helper.stdout.close()


def test_main_excludes_itself_and_its_whole_ancestor_chain(
    strays: types.ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    # ".*" matches every process's argv, including this one's (and whatever shell
    # wrapper launched it): without the self/ancestor exclusion, at least one of
    # them would always show up.
    strays.main([".*"])

    found = {int(line.split("\t")[0]) for line in capsys.readouterr().out.splitlines()}
    own_pid = strays.os.getpid()
    excluded = {own_pid, *strays.ancestors(own_pid, ppid_of=strays.read_ppid)}
    assert excluded.isdisjoint(found)


def test_main_finds_a_real_stray_process_by_its_argv(
    strays: types.ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    token = f"mscts-strays-test-{uuid.uuid4().hex}"
    with running_helper([sys.executable, "-I", "-S", "-c", _HELPER, token]) as helper:
        exit_code = strays.main([re.escape(token)])

    found = [int(line.split("\t")[0]) for line in capsys.readouterr().out.splitlines()]
    assert found == [helper.pid]
    assert exit_code == 1


def test_main_prints_one_line_per_process_even_when_an_argv_holds_a_newline(
    strays: types.ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    # Another process's argv may hold control characters (a newline, a tab);
    # each stray must still be exactly one "<pid>\t<cmd>" line.
    token = f"mscts-strays-test-{uuid.uuid4().hex}"
    with running_helper([sys.executable, "-I", "-S", "-c", _HELPER, token, "a\nb\tc"]) as helper:
        strays.main([re.escape(token)])
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert lines[0].split("\t", 1)[0] == str(helper.pid)
    assert "a\\nb\\tc" in lines[0]
