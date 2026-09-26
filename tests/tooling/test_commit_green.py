"""scripts/commit_green.py: THE way to commit, tested hermetically.

No real `mise run check` runs inside the unit tier: every test injects a fake check
(either a fake `run_check_fn`, or a monkeypatched `run_check`/`run_git_commit`, or a
tiny real Python script standing in for the check). The one end-to-end test runs real
`git` against a throwaway repo under `tmp_path`, with `GIT_*` scrubbed for its own setup
commands, exactly like `tests/tooling/test_mutate.py`'s pattern.
"""

import importlib.util
import os
import subprocess
import sys
import types
from collections.abc import Mapping
from pathlib import Path

import pytest

_COMMIT_GREEN_PATH = Path(__file__).resolve().parents[2] / "scripts" / "commit_green.py"


def _load_commit_green() -> types.ModuleType:
    """Load scripts/commit_green.py by path (scripts/ is not an importable package)."""
    spec = importlib.util.spec_from_file_location("commit_green", _COMMIT_GREEN_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def commit_green() -> types.ModuleType:
    # Not module-scoped: several tests monkeypatch its module-level functions.
    return _load_commit_green()


# -- split_argv / parse_args ----------------------------------------------------------


def test_split_argv_splits_on_the_first_double_dash(commit_green: types.ModuleType) -> None:
    own, git_args = commit_green.split_argv(["--tail", "10", "--", "-m", "msg"])
    assert own == ["--tail", "10"]
    assert git_args == ["-m", "msg"]


def test_split_argv_raises_without_a_double_dash(commit_green: types.ModuleType) -> None:
    with pytest.raises(commit_green.CommitError, match="--"):
        commit_green.split_argv(["-m", "msg"])


def test_parse_args_defaults_the_check_cmd_and_tail(commit_green: types.ModuleType) -> None:
    args = commit_green.parse_args(["--", "-m", "msg"])
    assert args.check_cmd == commit_green.DEFAULT_CHECK_CMD
    assert args.git_args == ("-m", "msg")
    assert args.tail_lines == commit_green.DEFAULT_TAIL_LINES


def test_parse_args_reads_an_overridden_check_cmd(commit_green: types.ModuleType) -> None:
    args = commit_green.parse_args(["--check-cmd", "python3 -c pass", "--", "-m", "msg"])
    assert args.check_cmd == ("python3", "-c", "pass")


def test_parse_args_reads_an_overridden_tail(commit_green: types.ModuleType) -> None:
    args = commit_green.parse_args(["--tail", "5", "--", "-m", "msg"])
    assert args.tail_lines == 5


def test_parse_args_raises_when_no_git_args_follow_the_double_dash(
    commit_green: types.ModuleType,
) -> None:
    with pytest.raises(commit_green.CommitError, match="no git commit arguments"):
        commit_green.parse_args(["--"])


def test_parse_args_exits_2_on_an_unrecognized_flag(commit_green: types.ModuleType) -> None:
    with pytest.raises(SystemExit) as excinfo:
        commit_green.parse_args(["--nope", "--", "-m", "msg"])
    assert excinfo.value.code == 2


# -- strip_git_env ----------------------------------------------------------------------


def test_strip_git_env_removes_only_git_prefixed_keys(commit_green: types.ModuleType) -> None:
    env = {"GIT_DIR": "/x/.git", "GIT_WORK_TREE": "/x", "PATH": "/usr/bin", "GITHUB_TOKEN": "t"}

    stripped = commit_green.strip_git_env(env)

    assert stripped == {"PATH": "/usr/bin", "GITHUB_TOKEN": "t"}


def test_strip_git_env_is_a_new_dict(commit_green: types.ModuleType) -> None:
    env = {"PATH": "/usr/bin"}
    assert commit_green.strip_git_env(env) is not env


# -- read_tail ----------------------------------------------------------------------------


def test_tail_of_returns_the_last_n_lines(commit_green: types.ModuleType) -> None:
    assert commit_green.tail_of("one\ntwo\nthree\nfour\n", 2) == "three\nfour"


def test_tail_of_returns_everything_when_the_text_is_shorter_than_n(
    commit_green: types.ModuleType,
) -> None:
    assert commit_green.tail_of("one\ntwo\n", 60) == "one\ntwo"


# -- commit_if_green (hermetic: fake run_check_fn/run_git_commit_fn) ---------------------


def test_commit_if_green_commits_when_the_check_exits_0(
    commit_green: types.ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    commit_calls: list[tuple[str, ...]] = []

    def fake_run_check(_cmd: object) -> tuple[int, str]:
        return 0, "lint ok\ntypes ok\ntests ok\n"

    def fake_run_git_commit(git_args: tuple[str, ...]) -> int:
        commit_calls.append(git_args)
        return 0

    exit_code = commit_green.commit_if_green(
        ("check",),
        ("-m", "msg"),
        tail_lines=60,
        run_check_fn=fake_run_check,
        run_git_commit_fn=fake_run_git_commit,
    )

    assert exit_code == 0
    assert commit_calls == [("-m", "msg")]
    assert "tests ok" in capsys.readouterr().out


def test_commit_if_green_does_not_commit_when_the_check_fails(
    commit_green: types.ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_run_check(_cmd: object) -> tuple[int, str]:
        return 1, "ruff: E999 syntax error\n"

    def fake_run_git_commit(_git_args: object) -> int:
        pytest.fail("must not commit when the check failed")

    exit_code = commit_green.commit_if_green(
        ("check",),
        ("-m", "msg"),
        tail_lines=60,
        run_check_fn=fake_run_check,
        run_git_commit_fn=fake_run_git_commit,
    )

    captured = capsys.readouterr()
    assert exit_code == 1  # the check's own exit code, not committed
    assert "E999 syntax error" in captured.out
    assert "not committing" in captured.err


def test_commit_if_green_returns_the_checks_own_exit_code_on_failure(
    commit_green: types.ModuleType,
) -> None:
    def fake_run_check(_cmd: object) -> tuple[int, str]:
        return 7, "boom\n"

    def fake_run_git_commit(_git_args: object) -> int:
        pytest.fail("must not commit")

    exit_code = commit_green.commit_if_green(
        ("check",),
        ("-m", "msg"),
        tail_lines=60,
        run_check_fn=fake_run_check,
        run_git_commit_fn=fake_run_git_commit,
    )

    assert exit_code == 7


def test_commit_if_green_returns_the_commits_own_exit_code(
    commit_green: types.ModuleType,
) -> None:
    def fake_run_check(_cmd: object) -> tuple[int, str]:
        return 0, "ok\n"

    def fake_run_git_commit(_git_args: object) -> int:
        return 3  # e.g. git itself refused for some reason

    exit_code = commit_green.commit_if_green(
        ("check",),
        ("-m", "msg"),
        tail_lines=60,
        run_check_fn=fake_run_check,
        run_git_commit_fn=fake_run_git_commit,
    )

    assert exit_code == 3


# -- main: GIT_* is stripped for the check but kept for the commit ----------------------


def test_main_strips_git_env_for_the_check_but_keeps_it_for_the_commit(
    commit_green: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    # As under `git rebase -x`: GIT_DIR is set in the ambient environment throughout.
    monkeypatch.setenv("GIT_DIR", "/somewhere/.git")
    check_envs: list[Mapping[str, str]] = []
    commit_envs: list[Mapping[str, str]] = []

    def fake_run_check(_cmd: object, path: Path, *, env: Mapping[str, str]) -> int:
        check_envs.append(env)
        path.write_text("ok\n")
        return 0

    def fake_run_git_commit(_git_args: object, *, env: Mapping[str, str]) -> int:
        commit_envs.append(env)
        return 0

    monkeypatch.setattr(commit_green, "run_check", fake_run_check)
    monkeypatch.setattr(commit_green, "run_git_commit", fake_run_git_commit)

    exit_code = commit_green.main(["--", "-m", "msg"])

    assert exit_code == 0
    assert "GIT_DIR" not in check_envs[0]  # dropped for the check's own subprocess tree
    assert commit_envs[0]["GIT_DIR"] == "/somewhere/.git"  # kept for `git commit` itself


def test_main_does_not_commit_when_the_check_fails(
    commit_green: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run_check(_cmd: object, path: Path, *, env: Mapping[str, str]) -> int:  # noqa: ARG001
        path.write_text("red\n")
        return 4

    def fake_run_git_commit(*_args: object, **_kwargs: object) -> int:
        pytest.fail("must not commit when the check failed")

    monkeypatch.setattr(commit_green, "run_check", fake_run_check)
    monkeypatch.setattr(commit_green, "run_git_commit", fake_run_git_commit)

    exit_code = commit_green.main(["--", "-m", "msg"])

    assert exit_code == 4


def test_main_cleans_up_its_temp_check_output_file(
    commit_green: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen_paths: list[Path] = []

    def fake_run_check(_cmd: object, path: Path, *, env: Mapping[str, str]) -> int:  # noqa: ARG001
        seen_paths.append(path)
        path.write_text("ok\n")
        return 0

    def fake_run_git_commit(*_args: object, **_kwargs: object) -> int:
        return 0

    monkeypatch.setattr(commit_green, "run_check", fake_run_check)
    monkeypatch.setattr(commit_green, "run_git_commit", fake_run_git_commit)

    commit_green.main(["--", "-m", "msg"])

    assert not seen_paths[0].exists()


# -- end-to-end: a real throwaway git repo, GIT_* scrubbed for its setup ----------------


def _git(*args: str, cwd: Path) -> None:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", *args],  # noqa: S607
        cwd=cwd,
        env=env,
        check=True,
    )


def _init_repo_with_one_commit(repo: Path) -> None:
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    (repo / "a.py").write_text("value = 1\n")
    _git("add", "a.py", cwd=repo)
    _git("commit", "-q", "-m", "initial", cwd=repo)


def test_main_end_to_end_commits_in_a_real_repo_when_the_check_passes(
    commit_green: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo_with_one_commit(repo)
    (repo / "a.py").write_text("value = 2\n")
    _git("add", "a.py", cwd=repo)
    check_script = tmp_path / "fake_check.py"
    check_script.write_text("import sys\nsys.stdout.write('check ok\\n')\nsys.exit(0)\n")
    monkeypatch.chdir(repo)
    monkeypatch.delenv("GIT_DIR", raising=False)

    exit_code = commit_green.main(
        ["--check-cmd", f"{sys.executable} {check_script}", "--", "-q", "-m", "second"]
    )

    assert exit_code == 0
    log = subprocess.run(
        ["git", "log", "--oneline"],  # noqa: S607
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "second" in log.stdout
    assert "initial" in log.stdout


def test_main_end_to_end_does_not_commit_in_a_real_repo_when_the_check_fails(
    commit_green: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo_with_one_commit(repo)
    (repo / "a.py").write_text("value = 2\n")
    _git("add", "a.py", cwd=repo)
    check_script = tmp_path / "fake_check.py"
    check_script.write_text("import sys\nsys.stdout.write('check failed\\n')\nsys.exit(1)\n")
    monkeypatch.chdir(repo)
    monkeypatch.delenv("GIT_DIR", raising=False)

    exit_code = commit_green.main(
        ["--check-cmd", f"{sys.executable} {check_script}", "--", "-q", "-m", "second"]
    )

    assert exit_code == 1
    log = subprocess.run(
        ["git", "log", "--oneline"],  # noqa: S607
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "second" not in log.stdout  # never committed
    status = subprocess.run(
        ["git", "status", "--porcelain"],  # noqa: S607
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "a.py" in status.stdout  # the staged edit is still there, uncommitted
