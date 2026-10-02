"""scripts/time_tier.py: argument handling, --durations output parsing, and the copy.

Hermetic: no real pytest subprocess anywhere (a fake `run` stands in for
`run_in_copy`), and the copy tests exercise the real `make_copy` against a throwaway
git repo under `tmp_path` (mirroring tests/tooling/test_mutate.py's own make_copy
tests) -- no network either way.
"""

import importlib.util
import os
import subprocess
import types
from pathlib import Path

import pytest

_TIME_TIER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "time_tier.py"


def _load_time_tier() -> types.ModuleType:
    """Load scripts/time_tier.py by path (scripts/ is not an importable package)."""
    spec = importlib.util.spec_from_file_location("time_tier", _TIME_TIER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def time_tier() -> types.ModuleType:
    return _load_time_tier()


# -- parse_args -----------------------------------------------------------------------


def test_parse_args_defaults_to_one_run(time_tier: types.ModuleType) -> None:
    args = time_tier.parse_args(["test:reference"])
    assert args.task == "test:reference"
    assert args.times == 1


def test_parse_args_reads_times(time_tier: types.ModuleType) -> None:
    args = time_tier.parse_args(["test:reference", "--times", "3"])
    assert args.task == "test:reference"
    assert args.times == 3


def test_parse_args_rejects_non_positive_times(time_tier: types.ModuleType) -> None:
    with pytest.raises(time_tier.TimeTierError, match="--times"):
        time_tier.parse_args(["test:reference", "--times", "0"])


def test_parse_args_requires_a_task(time_tier: types.ModuleType) -> None:
    with pytest.raises(SystemExit):
        time_tier.parse_args(["--times", "3"])


# -- task_run_commands ------------------------------------------------------------------


def test_task_run_commands_reads_a_string_run(time_tier: types.ModuleType, tmp_path: Path) -> None:
    mise_toml = tmp_path / "mise.toml"
    mise_toml.write_text('[tasks."test:reference"]\nrun = "uv run pytest -m reference"\n')
    assert time_tier.task_run_commands(mise_toml, "test:reference") == [
        "uv run pytest -m reference"
    ]


def test_task_run_commands_reads_a_list_run(time_tier: types.ModuleType, tmp_path: Path) -> None:
    mise_toml = tmp_path / "mise.toml"
    mise_toml.write_text('[tasks.fix]\nrun = ["uv run ruff format", "uv run ruff check --fix"]\n')
    assert time_tier.task_run_commands(mise_toml, "fix") == [
        "uv run ruff format",
        "uv run ruff check --fix",
    ]


def test_task_run_commands_rejects_a_missing_task(
    time_tier: types.ModuleType, tmp_path: Path
) -> None:
    mise_toml = tmp_path / "mise.toml"
    mise_toml.write_text('[tasks.fix]\nrun = "uv run ruff format"\n')
    with pytest.raises(time_tier.TimeTierError, match="no task"):
        time_tier.task_run_commands(mise_toml, "test:reference")


def test_task_run_commands_rejects_a_run_field_of_the_wrong_shape(
    time_tier: types.ModuleType, tmp_path: Path
) -> None:
    mise_toml = tmp_path / "mise.toml"
    mise_toml.write_text("[tasks.bad]\nrun = 5\n")
    with pytest.raises(time_tier.TimeTierError, match="string"):
        time_tier.task_run_commands(mise_toml, "bad")


# -- prepare_command --------------------------------------------------------------------


def test_prepare_command_inserts_no_sync_and_durations_for_pytest(
    time_tier: types.ModuleType,
) -> None:
    argv = time_tier.prepare_command("uv run pytest -m reference")
    assert argv == ["uv", "run", "--no-sync", "pytest", "-m", "reference", "--durations=10"]


def test_prepare_command_leaves_a_non_pytest_command_alone_besides_no_sync(
    time_tier: types.ModuleType,
) -> None:
    argv = time_tier.prepare_command("uv run ruff format --check")
    assert argv == ["uv", "run", "--no-sync", "ruff", "format", "--check"]


def test_prepare_command_leaves_a_non_uv_command_untouched(time_tier: types.ModuleType) -> None:
    argv = time_tier.prepare_command("echo hello")
    assert argv == ["echo", "hello"]


# -- parse_slowest_durations --------------------------------------------------------------


_JOIN_TEST_ID = "tests/reference/test_join_reference.py::test_a_joined_bot_stays_connected"
_SAMPLE_OUTPUT = f"""\
============================= test session starts ==============================
collected 5 items

tests/reference/test_join_reference.py ...                             [100%]

============================ slowest 10 durations =============================
30.02s call     {_JOIN_TEST_ID}
10.05s setup    tests/reference/conftest.py::reference
0.42s call     tests/reference/test_bot_reference.py::test_status_returns_protocol_777

(2 durations < 0.005s hidden.  Use -vv to show these durations.)
============================== 5 passed in 41.02s ===============================
"""


def test_parse_slowest_durations_extracts_the_entry_lines(time_tier: types.ModuleType) -> None:
    assert time_tier.parse_slowest_durations(_SAMPLE_OUTPUT) == [
        f"30.02s call     {_JOIN_TEST_ID}",
        "10.05s setup    tests/reference/conftest.py::reference",
        "0.42s call     tests/reference/test_bot_reference.py::test_status_returns_protocol_777",
    ]


def test_parse_slowest_durations_returns_empty_without_a_durations_section(
    time_tier: types.ModuleType,
) -> None:
    assert time_tier.parse_slowest_durations("============ 5 passed in 1.02s =============") == []


# -- make_copy (a real, throwaway git repo under tmp_path; no network) -----------------


def _git(*args: str, cwd: Path) -> None:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", *args],  # noqa: S607
        cwd=cwd,
        env=env,
        check=True,
    )


def test_make_copy_copies_tracked_and_untracked_non_ignored_files(
    time_tier: types.ModuleType, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    (repo / "a.py").write_text("tracked\n")
    (repo / ".gitignore").write_text("ignored.py\n")
    _git("add", "a.py", ".gitignore", cwd=repo)
    _git("commit", "-q", "-m", "initial", cwd=repo)
    (repo / "untracked.py").write_text("never added\n")
    (repo / "ignored.py").write_text("must not be copied\n")

    dest = tmp_path / "copy"
    time_tier.make_copy(repo, dest)

    assert (dest / "a.py").read_text() == "tracked\n"
    assert (dest / "untracked.py").read_text() == "never added\n"
    assert not (dest / "ignored.py").exists()
    assert (repo / "untracked.py").exists()  # the original repo is untouched


# -- run_tier_once (hermetic: a fake run and make_copy) --------------------------------


def test_run_tier_once_aggregates_timing_load_and_durations(
    time_tier: types.ModuleType, tmp_path: Path
) -> None:
    seen_commands: list[list[str]] = []

    def fake_make_copy(_repo_root: Path, dest: Path) -> None:
        dest.mkdir(parents=True)

    def fake_run(_copy_root: Path, argv: list[str]) -> subprocess.CompletedProcess[str]:
        seen_commands.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout=_SAMPLE_OUTPUT, stderr="")

    loads = iter([1.5, 2.5])

    result = time_tier.run_tier_once(
        tmp_path / "repo",
        ["uv run pytest -m reference"],
        fake_run,
        hooks=time_tier.CopyHooks(
            make_copy=fake_make_copy,
            get_load=lambda: next(loads),
            new_copy_root=lambda: tmp_path / "copy",
        ),
    )

    assert seen_commands == [
        ["uv", "run", "--no-sync", "pytest", "-m", "reference", "--durations=10"]
    ]
    assert result.load_before == 1.5
    assert result.load_after == 2.5
    assert result.total_s >= 0.0
    assert len(result.slowest) == 3
    assert not (tmp_path / "copy").exists()  # always cleaned up


def test_run_tier_once_cleans_up_the_copy_even_if_run_raises(
    time_tier: types.ModuleType, tmp_path: Path
) -> None:
    def fake_make_copy(_repo_root: Path, dest: Path) -> None:
        dest.mkdir(parents=True)

    def failing_run(_copy_root: Path, _argv: list[str]) -> subprocess.CompletedProcess[str]:
        msg = "boom"
        raise RuntimeError(msg)

    with pytest.raises(RuntimeError, match="boom"):
        time_tier.run_tier_once(
            tmp_path / "repo",
            ["uv run pytest -m reference"],
            failing_run,
            hooks=time_tier.CopyHooks(
                make_copy=fake_make_copy, new_copy_root=lambda: tmp_path / "copy"
            ),
        )

    assert not (tmp_path / "copy").exists()


@pytest.mark.parametrize("codes", [(0, 0), (1, 0), (0, 2)])
def test_main_reports_each_runs_last_pytest_summary_and_fails_if_any_command_failed(
    time_tier: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    codes: tuple[int, int],
) -> None:
    completed = iter(codes)
    copies: list[Path] = []
    original_run_tier_once = time_tier.run_tier_once

    def fake_make_copy(_repo: Path, destination: Path) -> None:
        destination.mkdir(parents=True)
        copies.append(destination)

    def fake_run(_venv: Path, _copy: Path, argv: list[str]) -> subprocess.CompletedProcess[str]:
        code = next(completed)
        summary = "1 failed in 0.02s" if code else "2 passed in 0.01s"
        output = f"== 99 passed in 1.00s ==\n== {summary} ==\ntrailing diagnostic\n"
        return subprocess.CompletedProcess(argv, code, stdout=output, stderr="")

    def run_once(repo: Path, commands: list[str], run: object) -> object:
        return original_run_tier_once(
            repo,
            commands,
            run,
            hooks=time_tier.CopyHooks(
                make_copy=fake_make_copy,
                get_load=lambda: 0.0,
                new_copy_root=lambda: tmp_path / f"run-{len(copies)}" / "copy",
            ),
        )

    monkeypatch.setattr(time_tier, "task_run_commands", lambda *_args: ["uv run pytest"])
    monkeypatch.setattr(time_tier, "_venv_path", lambda _repo: tmp_path)
    monkeypatch.setattr(time_tier, "run_in_copy", fake_run)
    monkeypatch.setattr(time_tier, "run_tier_once", run_once)

    status = time_tier.main(["test", "--times", "2"])

    assert (status != 0) == any(codes)
    output = capsys.readouterr().out
    lines = output.splitlines()
    for index, code in enumerate(codes, 1):
        heading = next(i for i, line in enumerate(lines) if line.startswith(f"run {index}/2:"))
        summary = "1 failed in 0.02s" if code else "2 passed in 0.01s"
        assert lines[heading + 1].strip() == summary, output
    assert "99 passed" not in output
    assert "trailing diagnostic" not in output
    assert len(copies) == 2
    assert all(not copy.exists() for copy in copies)


def test_a_later_passing_command_does_not_erase_failure_or_the_last_stderr_summary(
    time_tier: types.ModuleType, tmp_path: Path
) -> None:
    responses = iter(
        [
            subprocess.CompletedProcess([], 1, stdout=_SAMPLE_OUTPUT, stderr=""),
            subprocess.CompletedProcess(
                [], 0, stdout="diagnostic", stderr="== 2 passed in 0.03s ==\n"
            ),
        ]
    )

    def fake_make_copy(_repo: Path, destination: Path) -> None:
        destination.mkdir(parents=True)

    result = time_tier.run_tier_once(
        tmp_path / "repo",
        ["uv run pytest first", "uv run pytest second"],
        lambda _copy, _argv: next(responses),
        hooks=time_tier.CopyHooks(
            make_copy=fake_make_copy,
            get_load=lambda: 0.0,
            new_copy_root=lambda: tmp_path / "run" / "copy",
        ),
    )

    assert result.failed
    assert result.summary == "2 passed in 0.03s"


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        (_SAMPLE_OUTPUT, "5 passed in 41.02s"),
        (
            "20 passed, 200 deselected in 211.30s (0:03:31)\n",
            "20 passed, 200 deselected in 211.30s (0:03:31)",
        ),
        (
            "== 1 failed, 2 passed, 3 skipped, 1 error in 1.23s ==",
            "1 failed, 2 passed, 3 skipped, 1 error in 1.23s",
        ),
        ("no tests ran in 0.01s", "no tests ran in 0.01s"),
        ("All checks passed!\n", None),
    ],
)
def test_last_pytest_summary_accepts_verbose_and_quiet_results_without_inventing_one(
    time_tier: types.ModuleType, output: str, expected: str | None
) -> None:
    assert time_tier.last_pytest_summary(output) == expected
