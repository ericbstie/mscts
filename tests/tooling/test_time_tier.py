"""scripts/time_tier.py: argument handling, --durations output parsing, and the copy.

Hermetic: no real pytest subprocess anywhere (a fake `run` stands in for
`run_in_copy`), and the copy tests exercise the real `make_copy` against a throwaway
git repo under `tmp_path` (mirroring tests/tooling/test_mutate.py's own make_copy
tests) -- no network either way.
"""

import contextlib
import fcntl
import importlib.util
import os
import subprocess
import sys
import types
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any, Protocol

import pytest
from support.hermetic_git import hermetic_git

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


def test_make_copy_copies_tracked_and_untracked_non_ignored_files(
    time_tier: types.ModuleType, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    hermetic_git("init", "-q", cwd=repo)
    (repo / "a.py").write_text("tracked\n")
    (repo / ".gitignore").write_text("ignored.py\n")
    hermetic_git("add", "a.py", ".gitignore", cwd=repo)
    hermetic_git("commit", "-q", "-m", "initial", cwd=repo)
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


# -- revisions: parse_args, append_selection, run_order (#412) ---------------------------


def test_parse_args_defaults_to_the_working_tree(time_tier: types.ModuleType) -> None:
    args = time_tier.parse_args(["test:reference"])
    assert args.revisions == ()
    assert args.rounds == 1
    assert args.stress is False
    assert args.pytest_args == ()


def test_parse_args_reads_revisions_rounds_stress_and_the_selection(
    time_tier: types.ModuleType,
) -> None:
    args = time_tier.parse_args(
        [
            "test:statistical",
            "--rev",
            "origin/main",
            "--rev",
            "HEAD",
            "--rounds",
            "3",
            "--stress",
            "--stress-workers",
            "2",
            "--",
            "tests/selfcheck",
            "-k",
            "mobs/chase-open",
        ]
    )
    assert args.task == "test:statistical"
    assert args.revisions == ("origin/main", "HEAD")
    assert args.rounds == 3
    assert args.stress is True
    assert args.stress_workers == 2
    assert args.pytest_args == ("tests/selfcheck", "-k", "mobs/chase-open")


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["t", "--rev", "main"], "at least two"),
        (["t", "--rev", "main", "--rev", "main"], "twice"),
        (["t", "--rev", "a", "--rev", "b", "--rounds", "0"], "--rounds"),
        (["t", "--rev", "a", "--rev", "b", "--times", "2"], "--times"),
        (["t", "--rounds", "2"], "--rev"),
        (["t", "--stress"], "--rev"),
        (["t", "--rev", "a", "--rev", "b", "--stress-workers", "0"], "--stress-workers"),
    ],
)
def test_parse_args_rejects_a_comparison_it_cannot_run(
    time_tier: types.ModuleType, argv: list[str], message: str
) -> None:
    with pytest.raises(time_tier.TimeTierError, match=message):
        time_tier.parse_args(argv)


def test_append_selection_goes_after_the_pytest_arguments_of_pytest_commands_only(
    time_tier: types.ModuleType,
) -> None:
    commands = ["uv run ruff check", "uv run pytest -m statistical"]
    assert time_tier.append_selection(commands, ("tests/selfcheck", "-k", "a b")) == [
        "uv run ruff check",
        "uv run pytest -m statistical tests/selfcheck -k 'a b'",
    ]


def test_append_selection_without_a_selection_changes_nothing(time_tier: types.ModuleType) -> None:
    assert time_tier.append_selection(["uv run pytest"], ()) == ["uv run pytest"]


def test_run_order_alternates_the_revisions_round_by_round(time_tier: types.ModuleType) -> None:
    main = time_tier.Revision("main", "a" * 40)
    branch = time_tier.Revision("branch", "b" * 40)
    assert time_tier.run_order([main, branch], 3) == [
        (1, main),
        (1, branch),
        (2, main),
        (2, branch),
        (3, main),
        (3, branch),
    ]


def _repository_with_two_commits(tmp_path: Path) -> tuple[Path, str, str]:
    """A throwaway repo: `a.py` is "one" at the first commit, "two" at the second."""
    repo = tmp_path / "repo"
    repo.mkdir()
    hermetic_git("init", "-q", cwd=repo)
    (repo / "a.py").write_text("one\n")
    hermetic_git("add", "a.py", cwd=repo)
    hermetic_git("commit", "-q", "-m", "first", cwd=repo)
    hermetic_git("tag", "-a", "first", "-m", "first", cwd=repo)
    (repo / "a.py").write_text("two\n")
    hermetic_git("commit", "-q", "-am", "second", cwd=repo)
    (repo / "a.py").write_text("three, not committed\n")
    (repo / "untracked.py").write_text("never added\n")
    head = _commit_of("HEAD", repo)
    return repo, _commit_of("first^{commit}", repo), head


def _commit_of(name: str, repo: Path) -> str:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    done = subprocess.run(
        ["git", "rev-parse", name],  # noqa: S607
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def test_resolve_revisions_names_each_revisions_commit(
    time_tier: types.ModuleType, tmp_path: Path
) -> None:
    repo, first, head = _repository_with_two_commits(tmp_path)
    assert time_tier.resolve_revisions(repo, ["first", "HEAD"]) == [
        time_tier.Revision("first", first),
        time_tier.Revision("HEAD", head),
    ]
    assert len(first) == 40


def test_resolve_revisions_rejects_a_revision_git_does_not_know(
    time_tier: types.ModuleType, tmp_path: Path
) -> None:
    repo, _, _ = _repository_with_two_commits(tmp_path)
    with pytest.raises(time_tier.TimeTierError, match="no-such-branch"):
        time_tier.resolve_revisions(repo, ["HEAD", "no-such-branch"])


def test_copy_revision_holds_the_committed_files_of_that_commit_only(
    time_tier: types.ModuleType, tmp_path: Path
) -> None:
    repo, first, _ = _repository_with_two_commits(tmp_path)
    dest = tmp_path / "copy"
    time_tier.copy_revision(repo, first, dest)
    assert (dest / "a.py").read_text() == "one\n"
    assert not (dest / "untracked.py").exists()
    assert (repo / "a.py").read_text() == "three, not committed\n"


def test_a_command_in_a_copy_gets_the_extra_environment_it_is_given(
    time_tier: types.ModuleType, tmp_path: Path
) -> None:
    code = "import os; print(os.environ['EXTRA'])"
    done = time_tier.run_in_copy(
        tmp_path / "venv", tmp_path, [sys.executable, "-c", code], extra_env={"EXTRA": "here"}
    )
    assert done.stdout.strip() == "here"


def test_a_command_in_a_copy_never_syncs_the_environment(
    time_tier: types.ModuleType, tmp_path: Path
) -> None:
    code = "import os; print(os.environ['UV_NO_SYNC'], os.environ['PYTHONPATH'])"
    done = time_tier.run_in_copy(tmp_path / "venv", tmp_path, [sys.executable, "-c", code])
    assert done.stdout.strip() == f"1 {tmp_path / 'src'}"


# -- time_comparison: one hold, the revisions alternating, a fake runner (#412) -------------


def _recording(events: list[str], name: str) -> Callable[[], Any]:
    @contextlib.contextmanager
    def scope() -> Iterator[None]:
        events.append(f"{name} in")
        try:
            yield
        finally:
            events.append(f"{name} out")

    return scope


class _Named(Protocol):
    name: str


class _Seams:
    """The fakes a comparison runs on: copies that log, a runner that answers from `codes`."""

    def __init__(self, time_tier: types.ModuleType, tmp_path: Path, codes: Sequence[int]) -> None:
        self.time_tier = time_tier
        self.tmp_path = tmp_path
        self.codes = iter(codes)
        self.events: list[str] = []
        self.copies = 0

    def hooks_for(self, revision: _Named) -> object:
        def make_copy(_root: Path, dest: Path) -> None:
            dest.mkdir(parents=True)
            self.events.append(f"copy {revision.name}")

        def new_copy_root() -> Path:
            self.copies += 1
            return self.tmp_path / f"copy-{self.copies}" / "copy"

        return self.time_tier.CopyHooks(
            make_copy=make_copy, get_load=lambda: 0.5, new_copy_root=new_copy_root
        )

    def run(self, _copy: Path, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        code = next(self.codes)
        self.events.append("run")
        summary = "1 failed in 2.00s" if code else "1 passed in 2.00s"
        return subprocess.CompletedProcess(list(argv), code, stdout=f"== {summary} ==\n", stderr="")

    def plan(self, rounds: int) -> object:
        return self.time_tier.Comparison(
            repo_root=self.tmp_path / "repo",
            revisions=[
                self.time_tier.Revision("main", "a" * 40),
                self.time_tier.Revision("branch", "b" * 40),
            ],
            rounds=rounds,
            commands=["uv run pytest -m statistical"],
        )

    def time(self, rounds: int) -> list[Any]:
        return self.time_tier.time_comparison(
            self.plan(rounds),
            self.run,
            hold=_recording(self.events, "hold"),
            load=_recording(self.events, "load"),
            hooks_for=self.hooks_for,
        )


def test_a_comparison_holds_once_and_loads_the_cpus_only_while_a_round_runs(
    time_tier: types.ModuleType, tmp_path: Path
) -> None:
    seams = _Seams(time_tier, tmp_path, [0, 0, 0, 0])
    seams.time(2)
    assert seams.events == [
        "hold in",
        "copy main",
        "load in",
        "run",
        "load out",
        "copy branch",
        "load in",
        "run",
        "load out",
        "copy main",
        "load in",
        "run",
        "load out",
        "copy branch",
        "load in",
        "run",
        "load out",
        "hold out",
    ]


def test_a_comparison_returns_each_round_with_its_revision_and_result(
    time_tier: types.ModuleType, tmp_path: Path
) -> None:
    seams = _Seams(time_tier, tmp_path, [0, 1])
    rounds = seams.time(1)
    assert [(r.number, r.revision.name, r.result.failed) for r in rounds] == [
        (1, "main", False),
        (1, "branch", True),
    ]
    assert rounds[1].result.summary == "1 failed in 2.00s"


def test_a_comparison_releases_the_hold_when_a_round_raises(
    time_tier: types.ModuleType, tmp_path: Path
) -> None:
    seams = _Seams(time_tier, tmp_path, [])  # the first run finds no code to answer with
    with pytest.raises(StopIteration):
        seams.time(1)
    assert seams.events[-1] == "hold out"
    assert seams.events[-2] == "load out"


def _round(time_tier: types.ModuleType, number: int, name: str, seconds: float) -> object:
    result = time_tier.RunResult(
        total_s=seconds, load_before=0.0, load_after=0.0, slowest=[], summary=None, failed=False
    )
    return time_tier.Round(number, time_tier.Revision(name, "c" * 40), result)


def test_the_median_is_per_revision_in_the_order_they_were_given(
    time_tier: types.ModuleType,
) -> None:
    rounds = [
        _round(time_tier, 1, "main", 10.0),
        _round(time_tier, 1, "branch", 30.0),
        _round(time_tier, 2, "main", 50.0),
        _round(time_tier, 2, "branch", 20.0),
        _round(time_tier, 3, "main", 20.0),
        _round(time_tier, 3, "branch", 40.0),
    ]
    medians = time_tier.median_seconds(rounds)
    assert list(medians.items()) == [("main", 20.0), ("branch", 30.0)]


def test_a_round_report_names_the_revision_commit_time_summary_and_load(
    time_tier: types.ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    result = time_tier.RunResult(
        total_s=12.34,
        load_before=0.25,
        load_after=7.5,
        slowest=[],
        summary="1 passed in 12.00s",
        failed=False,
    )
    round_ = time_tier.Round(
        2, time_tier.Revision("origin/main", "abcdef0123456789" * 2 + "abcd"), result
    )
    time_tier.print_round_report(round_, 3)
    assert capsys.readouterr().out.splitlines() == [
        "round 2/3 origin/main (abcdef012345): 12.3s, load avg before 0.25, after 7.50",
        "  1 passed in 12.00s",
    ]


def test_the_medians_report_names_each_revision_and_its_commit(
    time_tier: types.ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    time_tier.print_medians(
        [_round(time_tier, 1, "main", 10.0), _round(time_tier, 1, "branch", 12.0)]
    )
    assert capsys.readouterr().out.splitlines() == [
        "median of 1 round(s):",
        "  main (cccccccccccc): 10.0s",
        "  branch (cccccccccccc): 12.0s",
    ]


# -- main with revisions (fakes for git, the copy and the runner; the lock is real) ------


@pytest.mark.parametrize("codes", [(0, 0, 0, 0), (0, 0, 1, 0)])
def test_main_times_the_revisions_under_one_live_lock_hold_and_prints_everything(
    time_tier: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    codes: tuple[int, ...],
) -> None:
    cache = tmp_path / "cache"
    monkeypatch.setenv("MSCTS_CACHE", str(cache))
    monkeypatch.delenv("MSCTS_LIVE_LOCK", raising=False)
    monkeypatch.delenv("MSCTS_LIVE_LOCK_HELD", raising=False)
    answers = iter(codes)
    seen: list[str] = []
    selections: list[list[str]] = []
    extras: list[dict[str, str] | None] = []

    def fake_copy(_repo: Path, commit: str, dest: Path) -> None:
        dest.mkdir(parents=True)
        seen.append(f"copy {commit[:1]}")

    def fake_run(
        _venv: Path,
        _copy: Path,
        argv: list[str],
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        extras.append(extra_env)
        with (cache / "live-tier.lock").open("r+") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                held = "locked"
            else:
                held = "free"
        seen.append(f"run {held} {_stress_children()} {os.environ.get('MSCTS_LIVE_LOCK_HELD')}")
        selections.append(argv[6:9])
        code = next(answers)
        summary = "1 failed in 2.00s" if code else "1 passed in 2.00s"
        return subprocess.CompletedProcess(argv, code, stdout=f"== {summary} ==\n", stderr="")

    monkeypatch.setattr(
        time_tier,
        "resolve_revisions",
        lambda _repo, names: [time_tier.Revision(n, f"{i}" * 40) for i, n in enumerate(names)],
    )
    monkeypatch.setattr(time_tier, "copy_revision", fake_copy)
    monkeypatch.setattr(time_tier, "task_run_commands", lambda *_args: ["uv run pytest -m x"])
    monkeypatch.setattr(time_tier, "_venv_path", lambda _repo: tmp_path)
    monkeypatch.setattr(time_tier, "run_in_copy", fake_run)

    status = time_tier.main(
        [
            "t",
            "--rev",
            "main",
            "--rev",
            "branch",
            "--rounds",
            "2",
            "--stress",
            "--stress-workers",
            "2",
            "--",
            "tests/selfcheck",
            "-k",
            "mobs/chase-open",
        ]
    )

    assert status == int(any(codes))
    held_by = str(os.getpid())
    assert seen == [
        "copy 0",
        f"run locked 2 {held_by}",
        "copy 1",
        f"run locked 2 {held_by}",
        "copy 0",
        f"run locked 2 {held_by}",
        "copy 1",
        f"run locked 2 {held_by}",
    ]
    assert selections == [["tests/selfcheck", "-k", "mobs/chase-open"]] * 4
    assert extras == [{"MSCTS_LIVE_LOCK": "0"}] * 4
    lines = capsys.readouterr().out.splitlines()
    assert lines[:2] == ["main -> " + "0" * 40, "branch -> " + "1" * 40]
    assert sum(line.startswith("round ") for line in lines) == 4
    assert lines[-3] == "median of 2 round(s):"
    assert (cache / "live-tier.lock").read_text() == ""
    assert _stress_children() == 0


def _stress_children() -> int:
    """The busy-loop processes this process started: other workers' series are not counted."""
    count = 0
    for entry in Path("/proc").iterdir():
        try:
            environ = (entry / "environ").read_bytes().split(b"\0")
            parent = (entry / "stat").read_text().rpartition(")")[2].split()[1]
        except OSError:
            continue
        if parent == str(os.getpid()) and any(
            e.startswith(b"MSCTS_REPEAT_STRESS=") for e in environ
        ):
            count += 1
    return count
