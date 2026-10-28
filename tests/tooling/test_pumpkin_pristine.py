"""scripts/research/pumpkin_pristine.py: runs a binary once and diffs the config it writes."""

import importlib.util
import os
import time
import types
from pathlib import Path
from typing import cast

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "research" / "pumpkin_pristine.py"

COMMITTED = 'seed = "1"\ntps = 20.0\n\n[logging]\nlevel = "info"\n'


@pytest.fixture(scope="module")
def pristine() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("research_pumpkin_pristine", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_binary(tmp_path: Path, body: str) -> Path:
    """A `pumpkin` that is a shell script running `body` in its working directory."""
    binary = tmp_path / "bin" / "pumpkin"
    binary.parent.mkdir()
    binary.write_text(f"#!/bin/sh\n{body}\n")
    binary.chmod(0o755)
    return binary


def _writes_config(config: str, *, then: str, pid_file: Path | None = None) -> str:
    record_pid = f"echo $$ > {pid_file}\n" if pid_file else ""
    return f"{record_pid}cat > pumpkin.toml <<'EOF'\n{config}EOF\n{then}"


def _run(
    pristine: types.ModuleType, binary: Path, tmp_path: Path, timeout: float = 20
) -> tuple[str | None, str]:
    """The config the fake wrote (None if none) and its output."""
    workdir = tmp_path / "work"
    workdir.mkdir()
    result = pristine.run_pristine(
        binary, workdir, use_unshare=False, timeout=timeout, path=os.environ["PATH"]
    )
    return cast("tuple[str | None, str]", (result.config, result.output))


def _gone(pid: int) -> bool:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def test_the_diff_ignores_seed_and_shows_a_new_key(pristine: types.ModuleType) -> None:
    fresh = 'seed = "2"\ntps = 20.0\nnew_key = true\n\n[logging]\nlevel = "info"\n'
    diff = pristine.config_diff(COMMITTED, fresh, fresh_name="b70c7e1")
    assert diff.splitlines()[:2] == ["--- pumpkin.toml (committed)", "+++ pumpkin.toml (b70c7e1)"]
    assert "+new_key = true" in diff.splitlines()
    assert not [line for line in diff.splitlines() if "seed" in line]


def test_the_diff_shows_a_removed_and_a_changed_key(pristine: types.ModuleType) -> None:
    diff = pristine.config_diff(COMMITTED, 'seed = "2"\ntps = 40.0\n\n[logging]\n', fresh_name="x")
    lines = diff.splitlines()
    assert "-tps = 20.0" in lines
    assert "+tps = 40.0" in lines
    assert '-level = "info"' in lines


def test_the_diff_is_empty_when_only_the_seed_differs(pristine: types.ModuleType) -> None:
    assert pristine.config_diff(COMMITTED, COMMITTED.replace('"1"', '"2"'), fresh_name="x") == ""


def test_the_diff_keeps_a_seed_key_inside_a_table(pristine: types.ModuleType) -> None:
    committed = 'seed = "1"\n\n[world]\nseed = 5\n'
    fresh = 'seed = "2"\n\n[world]\nseed = 6\n'
    diff = pristine.config_diff(committed, fresh, fresh_name="x")
    assert "-seed = 5" in diff.splitlines()
    assert "+seed = 6" in diff.splitlines()


def test_the_command_runs_the_binary_inside_a_new_network_namespace(
    pristine: types.ModuleType,
) -> None:
    assert pristine.pristine_command(Path("/x/pumpkin"), use_unshare=True) == [
        "unshare",
        "-rn",
        "/x/pumpkin",
    ]
    assert pristine.pristine_command(Path("/x/pumpkin"), use_unshare=False) == ["/x/pumpkin"]


def test_a_config_written_by_a_binary_that_keeps_running_is_read_and_the_binary_stopped(
    pristine: types.ModuleType, tmp_path: Path
) -> None:
    pid_file = tmp_path / "pid"
    binary = _fake_binary(tmp_path, _writes_config(COMMITTED, then="sleep 300", pid_file=pid_file))
    started = time.monotonic()
    config, _ = _run(pristine, binary, tmp_path)
    assert config == COMMITTED
    assert time.monotonic() - started < 15
    assert _gone(int(pid_file.read_text()))


def test_a_config_file_that_is_still_empty_is_not_read_yet(
    pristine: types.ModuleType, tmp_path: Path
) -> None:
    body = f": > pumpkin.toml\nsleep 0.5\n{_writes_config(COMMITTED, then='exit 0')}"
    config, _ = _run(pristine, _fake_binary(tmp_path, body), tmp_path)
    assert config == COMMITTED


def test_a_config_written_by_a_binary_that_then_exits_is_read(
    pristine: types.ModuleType, tmp_path: Path
) -> None:
    binary = _fake_binary(tmp_path, _writes_config(COMMITTED, then="echo bind failed; exit 1"))
    config, _ = _run(pristine, binary, tmp_path)
    assert config == COMMITTED


def test_a_binary_that_exits_without_a_config_gives_none_and_its_output(
    pristine: types.ModuleType, tmp_path: Path
) -> None:
    binary = _fake_binary(tmp_path, "echo no config today; exit 3")
    started = time.monotonic()
    config, output = _run(pristine, binary, tmp_path)
    assert config is None
    assert "no config today" in output
    assert time.monotonic() - started < 15


def test_a_binary_that_never_writes_is_stopped_at_the_timeout(
    pristine: types.ModuleType, tmp_path: Path
) -> None:
    pid_file = tmp_path / "pid"
    binary = _fake_binary(tmp_path, f"echo $$ > {pid_file}\nsleep 300")
    config, _ = _run(pristine, binary, tmp_path, timeout=0.5)
    assert config is None
    assert _gone(int(pid_file.read_text()))


def test_the_binary_sees_no_environment_but_path(
    pristine: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MSCTS_LEAK", "1")
    seen = tmp_path / "seen"
    body = _writes_config(
        COMMITTED,
        then=f'if [ -n "$MSCTS_LEAK" ]; then echo leaked > {seen}; else echo clean > {seen}; fi',
    )
    _run(pristine, _fake_binary(tmp_path, body), tmp_path)
    assert seen.read_text() == "clean\n"


def test_main_prints_the_diff_and_exits_1_when_the_config_differs(
    pristine: types.ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    committed = tmp_path / "pumpkin.toml"
    committed.write_text(COMMITTED)
    fresh = COMMITTED.replace('"1"', '"2"') + "extra = 1\n"
    binary = _fake_binary(tmp_path, _writes_config(fresh, then="exit 0"))
    rc = pristine.main([str(binary), "--committed", str(committed)])
    assert rc == 1
    assert "+extra = 1" in capsys.readouterr().out.splitlines()


def test_main_says_so_and_exits_0_when_nothing_but_the_seed_differs(
    pristine: types.ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    committed = tmp_path / "pumpkin.toml"
    committed.write_text(COMMITTED)
    binary = _fake_binary(tmp_path, _writes_config(COMMITTED.replace('"1"', '"2"'), then="exit 0"))
    rc = pristine.main([str(binary), "--committed", str(committed)])
    assert rc == 0
    assert capsys.readouterr().out == "no difference (ignoring seed)\n"


def test_main_exits_2_and_shows_the_output_when_the_binary_wrote_no_config(
    pristine: types.ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    committed = tmp_path / "pumpkin.toml"
    committed.write_text(COMMITTED)
    binary = _fake_binary(tmp_path, "echo cannot start; exit 1")
    rc = pristine.main([str(binary), "--committed", str(committed)])
    assert rc == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "wrote no pumpkin.toml" in captured.err
    assert "cannot start" in captured.err
