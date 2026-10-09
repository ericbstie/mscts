"""scripts/commit_green.py: THE way to commit, tested hermetically.

No real `mise run check` runs inside the unit tier: every test injects a fake check
(either a fake `run_check_fn`, or a monkeypatched `run_check`/`run_git_commit`, or a
tiny real Python script standing in for the check). End-to-end tests run real
`git` against throwaway repos under `tmp_path`, with `GIT_*` scrubbed for their setup
commands, exactly like `tests/tooling/test_mutate.py`'s pattern.
"""

import importlib.util
import os
import re
import shlex
import subprocess
import sys
import types
import venv
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


@pytest.fixture
def commit_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Give main's index capture a throwaway repository in a path with spaces."""
    repo = tmp_path / "repo with spaces "
    _init_repo_with_one_commit(repo)
    monkeypatch.chdir(repo)
    for key in tuple(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key)
    return repo


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


@pytest.mark.parametrize(
    "selection",
    [
        "-a",
        "--all",
        "-i",
        "--include",
        "-o",
        "--only",
        "a.py",
        "-amanother message",
        "-qva",
        "--on",
        "--inc",
        "--interactive",
        "-p",
        "--patch",
        "--pathspec-from-file=paths.txt",
        "--pathspec-file-nul",
        "--fixup=reword:HEAD",
    ],
)
def test_parse_args_refuses_arguments_that_change_the_committed_tree(
    commit_green: types.ModuleType, selection: str
) -> None:
    with pytest.raises(commit_green.CommitError, match=re.escape(selection)) as excinfo:
        commit_green.parse_args(["--", "-m", "message", selection])
    assert "stage the intended files first" in str(excinfo.value)


@pytest.mark.parametrize(
    "git_args",
    [
        ("-m", "--all"),
        ("-m", "a.py"),
        ("-mmessage with -a",),
        ("-F", "message.txt"),
        ("-Fmessage.txt",),
        ("--message", "message"),
        ("--message=message",),
        ("--mess", "message"),
        ("--amend", "--no-edit"),
        ("-qvs", "--amend", "-C", "HEAD"),
        ("--fixup", "HEAD"),
        ("--fixup=amend:HEAD", "--no-edit"),
        ("--author", "Test <test@example.com>", "-m", "msg"),
        ("--trailer", "Reviewed-by: Test", "-m", "msg"),
        ("--gpg-sign=key", "-m", "msg"),
        ("-Skey", "-m", "msg"),
        ("-uno", "-m", "msg"),
        ("-U3", "-v", "-m", "msg"),
        ("--unified=3", "-v", "-m", "msg"),
        ("-m", "msg", "--"),
    ],
)
def test_parse_args_keeps_message_and_amend_options(
    commit_green: types.ModuleType, git_args: tuple[str, ...]
) -> None:
    assert commit_green.parse_args(["--", *git_args]).git_args == git_args


@pytest.mark.parametrize(
    ("git_args", "refused"),
    [
        (("-F", "message.txt", "--", "a.py"), "a.py"),
        (("-m", "--all", "a.py"), "a.py"),
        (("--fixup", "reword:HEAD"), "--fixup"),
        (("--fix", "reword:HEAD"), "--fix"),
    ],
)
def test_parse_args_refuses_paths_after_option_values_and_reword_fixups(
    commit_green: types.ModuleType, git_args: tuple[str, ...], refused: str
) -> None:
    with pytest.raises(commit_green.CommitError, match=re.escape(refused)) as excinfo:
        commit_green.parse_args(["--", *git_args])
    assert "stage the intended files first" in str(excinfo.value)


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
    commit_green: types.ModuleType, commit_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # As under `git rebase -x`: GIT_DIR is set in the ambient environment throughout.
    monkeypatch.setenv("GIT_DIR", str(commit_repo / ".git"))
    check_envs: list[Mapping[str, str]] = []
    commit_envs: list[Mapping[str, str]] = []

    def fake_run_check(_cmd: object, path: Path, *, env: Mapping[str, str], cwd: Path) -> int:
        assert cwd != commit_repo
        check_envs.append(env)
        path.write_text("ok\n")
        return 0

    def fake_run_git_commit(_git_args: object, *, env: Mapping[str, str], cwd: Path) -> int:
        assert cwd == commit_repo
        commit_envs.append(env)
        return 0

    monkeypatch.setattr(commit_green, "run_check", fake_run_check)
    monkeypatch.setattr(commit_green, "run_git_commit", fake_run_git_commit)

    exit_code = commit_green.main(["--", "-m", "msg"])

    assert exit_code == 0
    assert "GIT_DIR" not in check_envs[0]  # dropped for the check's own subprocess tree
    assert commit_envs[0]["GIT_DIR"] == str(commit_repo / ".git")


@pytest.mark.usefixtures("commit_repo")
def test_main_does_not_commit_when_the_check_fails(
    commit_green: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run_check(_cmd: object, path: Path, *, env: Mapping[str, str], cwd: Path) -> int:
        del env, cwd
        path.write_text("red\n")
        return 4

    def fake_run_git_commit(*_args: object, **_kwargs: object) -> int:
        pytest.fail("must not commit when the check failed")

    monkeypatch.setattr(commit_green, "run_check", fake_run_check)
    monkeypatch.setattr(commit_green, "run_git_commit", fake_run_git_commit)

    exit_code = commit_green.main(["--", "-m", "msg"])

    assert exit_code == 4


@pytest.mark.usefixtures("commit_repo")
def test_main_cleans_up_its_temp_check_output_file(
    commit_green: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen_paths: list[Path] = []

    def fake_run_check(_cmd: object, path: Path, *, env: Mapping[str, str], cwd: Path) -> int:
        del env, cwd
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


def _git(*args: str, cwd: Path, env: Mapping[str, str] | None = None) -> str:
    clean_env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    result = subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", *args],  # noqa: S607
        cwd=cwd,
        env=clean_env if env is None else dict(env),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


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


def test_main_refuses_a_staged_error_hidden_by_an_unstaged_fix(
    commit_green: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "repo"
    _init_repo_with_one_commit(repo)
    source = repo / "a.py"
    source.write_text('value: int = "red"\n')
    _git("add", "a.py", cwd=repo)
    source.write_text("value: int = 2\n")
    untracked = repo / "untracked.py"
    untracked.write_text("keep this untracked file unchanged\n")
    index = repo / ".git/index"
    before_index = index.read_bytes()
    before_source = source.read_bytes()
    before_untracked = untracked.read_bytes()
    check_script = tmp_path / "check_source.py"
    check_script.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "red = '\"red\"' in Path('a.py').read_text()\n"
        "print('staged check is red' if red else 'check is green')\n"
        "sys.exit(1 if red else 0)\n"
    )
    monkeypatch.chdir(repo)
    for key in tuple(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key)

    exit_code = commit_green.main(
        ["--check-cmd", f"{sys.executable} {check_script}", "--", "-q", "-m", "second"]
    )

    assert exit_code == 1
    assert "staged check is red" in capsys.readouterr().out
    assert index.read_bytes() == before_index
    assert source.read_bytes() == before_source
    assert untracked.read_bytes() == before_untracked
    log = subprocess.run(
        ["git", "log", "--oneline"],  # noqa: S607
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "second" not in log.stdout


def test_main_commits_only_the_staged_files_despite_unstaged_and_untracked_errors(
    commit_green: types.ModuleType, commit_repo: Path, tmp_path: Path
) -> None:
    source = commit_repo / "a.py"
    source.write_text("value = 2\n")
    _git("add", "a.py", cwd=commit_repo)
    source.write_text("unstaged error\n")
    untracked = commit_repo / "untracked.py"
    untracked.write_text("untracked error\n")
    check_script = tmp_path / "check_index.py"
    check_script.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "green = Path('a.py').read_text() == 'value = 2\\n'\n"
        "green = green and not Path('untracked.py').exists()\n"
        "print('index check passed' if green else 'wrong files checked')\n"
        "sys.exit(0 if green else 1)\n"
    )

    code = commit_green.main(
        ["--check-cmd", f"{sys.executable} {check_script}", "--", "-q", "-m", "second"]
    )

    assert code == 0
    assert _git("show", "HEAD:a.py", cwd=commit_repo) == "value = 2\n"
    assert source.read_text() == "unstaged error\n"
    assert untracked.read_text() == "untracked error\n"
    assert _git("status", "--porcelain", cwd=commit_repo) == " M a.py\n?? untracked.py\n"


def test_main_checks_and_commits_the_callers_alternate_index_under_rebase_env(
    commit_green: types.ModuleType,
    commit_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = commit_repo / "a.py"
    source.write_text("value = 2\n")
    _git("add", "a.py", cwd=commit_repo)
    alternate = tmp_path / "alternate-index"
    env = {**os.environ, "GIT_INDEX_FILE": str(alternate)}
    _git("read-tree", "HEAD", cwd=commit_repo, env=env)
    source.write_text("value = 3\n")
    _git("add", "a.py", cwd=commit_repo, env=env)
    before = alternate.read_bytes()
    check_script = tmp_path / "check_alternate.py"
    check_script.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "sys.exit(0 if Path('a.py').read_text() == 'value = 3\\n' else 1)\n"
    )
    monkeypatch.setenv("GIT_DIR", str(commit_repo / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(commit_repo))
    monkeypatch.setenv("GIT_INDEX_FILE", str(alternate))

    code = commit_green.main(
        ["--check-cmd", f"{sys.executable} {check_script}", "--", "-q", "-m", "alternate"]
    )

    assert code == 0
    assert _git("show", "HEAD:a.py", cwd=commit_repo) == "value = 3\n"
    assert _git("show", ":a.py", cwd=commit_repo) == "value = 2\n"
    assert alternate.read_bytes() == before
    assert not alternate.with_name(f"{alternate.name}.lock").exists()


def test_main_leaves_an_existing_index_lock_alone(
    commit_green: types.ModuleType, commit_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lock = commit_repo / ".git/index.lock"
    lock.write_bytes(b"another Git command owns this lock")

    assert commit_green.main(["--", "-m", "second"]) == 2

    err = capsys.readouterr().err
    assert "index is already locked" in err
    assert "interrupted `mise run commit`" in err
    assert f"rm {lock}" in err
    assert lock.read_bytes() == b"another Git command owns this lock"


def test_main_cleans_up_the_snapshot_and_index_lock_when_the_check_raises(
    commit_green: types.ModuleType, commit_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshots: list[Path] = []

    def interrupted_check(_cmd: object, _path: Path, *, env: Mapping[str, str], cwd: Path) -> int:
        del env
        snapshots.append(cwd)
        raise KeyboardInterrupt

    monkeypatch.setattr(commit_green, "run_check", interrupted_check)
    with pytest.raises(KeyboardInterrupt):
        commit_green.main(["--", "-m", "second"])

    assert not snapshots[0].exists()
    assert not (commit_repo / ".git/index.lock").exists()


def test_main_prevents_new_staging_during_the_check_and_commits_the_captured_index(
    commit_green: types.ModuleType, commit_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = commit_repo / "a.py"
    source.write_text("value = 2\n")
    _git("add", "a.py", cwd=commit_repo)

    def check_while_someone_stages(
        _cmd: object, path: Path, *, env: Mapping[str, str], cwd: Path
    ) -> int:
        assert (cwd / "a.py").read_text() == "value = 2\n"
        source.write_text("value = 3\n")
        stage = subprocess.run(
            ["git", "add", "a.py"],  # noqa: S607
            cwd=commit_repo,
            env=dict(env),
            capture_output=True,
            text=True,
            check=False,
        )
        assert stage.returncode != 0
        assert "index.lock" in stage.stderr
        path.write_text("captured index passed\n")
        return 0

    monkeypatch.setattr(commit_green, "run_check", check_while_someone_stages)
    assert commit_green.main(["--", "-q", "-m", "second"]) == 0

    assert _git("show", "HEAD:a.py", cwd=commit_repo) == "value = 2\n"
    assert source.read_text() == "value = 3\n"
    assert not (commit_repo / ".git/index.lock").exists()


def test_main_imports_staged_source_instead_of_an_unstaged_editable_source(
    commit_green: types.ModuleType,
    commit_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    package = commit_repo / "src/index_source"
    package.mkdir(parents=True)
    source = package / "__init__.py"
    source.write_text('VALUE = "red"\n')
    _git("add", "src", cwd=commit_repo)
    source.write_text('VALUE = "green"\n')
    monkeypatch.setenv("PYTHONPATH", str(commit_repo / "src"))
    check_script = tmp_path / "check_import.py"
    check_script.write_text(
        "import index_source\n"
        "import sys\n"
        "print('staged import is red' if index_source.VALUE == 'red' else 'wrong source')\n"
        "sys.exit(1 if index_source.VALUE == 'red' else 0)\n"
    )

    code = commit_green.main(
        ["--check-cmd", f"{sys.executable} {check_script}", "--", "-q", "-m", "second"]
    )

    assert code == 1
    assert "staged import is red" in capsys.readouterr().out
    assert source.read_text() == 'VALUE = "green"\n'
    assert "second" not in _git("log", "--oneline", cwd=commit_repo)


def test_main_amends_the_staged_tree_and_keeps_an_unstaged_change(
    commit_green: types.ModuleType, commit_repo: Path, tmp_path: Path
) -> None:
    source = commit_repo / "a.py"
    source.write_text("value = 2\n")
    _git("add", "a.py", cwd=commit_repo)
    source.write_text("value = 3\n")
    check_script = tmp_path / "check_amend.py"
    check_script.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "sys.exit(0 if Path('a.py').read_text() == 'value = 2\\n' else 1)\n"
    )

    code = commit_green.main(
        ["--check-cmd", f"{sys.executable} {check_script}", "--", "--amend", "--no-edit"]
    )

    assert code == 0
    assert _git("rev-list", "--count", "HEAD", cwd=commit_repo) == "1\n"
    assert _git("log", "-1", "--format=%s", cwd=commit_repo) == "initial\n"
    assert _git("show", "HEAD:a.py", cwd=commit_repo) == "value = 2\n"
    assert source.read_text() == "value = 3\n"


def test_main_exposes_the_installed_environment_at_the_snapshots_venv_path(
    commit_green: types.ModuleType, commit_repo: Path, tmp_path: Path
) -> None:
    venv = commit_repo / ".venv"
    helper = venv / "bin/helper"
    helper.parent.mkdir(parents=True)
    helper.write_text("already installed\n")
    (commit_repo / "a.py").write_text("value = 2\n")
    _git("add", "a.py", cwd=commit_repo)
    check_script = tmp_path / "check_dependencies.py"
    check_script.write_text(
        "from pathlib import Path\n"
        "import os, sys\n"
        "venv = Path('.venv')\n"
        "green = venv.is_dir() and venv.resolve() == Path(os.environ['UV_PROJECT_ENVIRONMENT'])\n"
        "green = green and (venv / 'bin/helper').read_text() == 'already installed\\n'\n"
        "sys.exit(0 if green else 1)\n"
    )

    code = commit_green.main(
        ["--check-cmd", f"{sys.executable} {check_script}", "--", "-q", "-m", "second"]
    )

    assert code == 0
    assert helper.read_text() == "already installed\n"
    assert _git("show", "HEAD:a.py", cwd=commit_repo) == "value = 2\n"


def test_main_does_not_load_an_untracked_package_from_the_editable_installation(
    commit_green: types.ModuleType,
    commit_repo: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    package = commit_repo / "src/index_source"
    package.mkdir(parents=True)
    source = package / "values.py"
    source.write_text('VALUE = "red"\n')
    _git("add", "src", cwd=commit_repo)
    source.write_text('VALUE = "green"\n')
    (package / "__init__.py").touch()
    environment = commit_repo / ".venv"
    venv.EnvBuilder(with_pip=False).create(environment)
    site_packages = next(environment.glob("lib/python*/site-packages"))
    (site_packages / "mscts.pth").write_text(f"{commit_repo / 'src'}\n")
    check_script = tmp_path / "check_editable.py"
    check_script.write_text(
        "from index_source.values import VALUE\n"
        "import sys\n"
        "print('staged namespace is red' if VALUE == 'red' else 'editable source leaked')\n"
        "sys.exit(1 if VALUE == 'red' else 0)\n"
    )

    code = commit_green.main(
        [
            "--check-cmd",
            shlex.join([str(environment / "bin/python"), str(check_script)]),
            "--",
            "-q",
            "-m",
            "second",
        ]
    )

    assert code == 1
    assert "staged namespace is red" in capsys.readouterr().out
    assert source.read_text() == 'VALUE = "green"\n'
    assert (package / "__init__.py").exists()
    assert "second" not in _git("log", "--oneline", cwd=commit_repo)


def test_main_commits_in_a_shallow_clone(
    commit_green: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    origin = tmp_path / "origin"
    _init_repo_with_one_commit(origin)
    (origin / "a.py").write_text("value = 2\n")
    _git("commit", "-q", "-am", "second", cwd=origin)
    shallow = tmp_path / "shallow"
    _git("clone", "-q", "--depth", "1", f"file://{origin}", str(shallow), cwd=tmp_path)
    (shallow / "a.py").write_text("value = 3\n")
    _git("add", "a.py", cwd=shallow)
    check_script = tmp_path / "fake_check.py"
    check_script.write_text("import sys\nsys.exit(0)\n")
    monkeypatch.chdir(shallow)
    for key in [key for key in os.environ if key.startswith("GIT_")]:
        monkeypatch.delenv(key)

    exit_code = commit_green.main(
        ["--check-cmd", f"{sys.executable} {check_script}", "--", "-q", "-m", "third"]
    )

    assert exit_code == 0
    assert "third" in _git("log", "--oneline", cwd=shallow)
