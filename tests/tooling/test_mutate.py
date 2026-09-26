"""scripts/mutate.py's pure and filesystem parts.

Hermetic: no real pytest subprocess anywhere (a fake `run`/`run_in_copy`, or a fake
`subprocess.run`, stands in throughout), and no network. A few `make_copy` tests run real
`git` against a throwaway repo under `tmp_path`, which needs no network either.
"""

import importlib.util
import json
import os
import subprocess
import types
from collections.abc import Sequence
from pathlib import Path

import pytest

_MUTATE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "mutate.py"


def _load_mutate() -> types.ModuleType:
    """Load scripts/mutate.py by path (scripts/ is not an importable package)."""
    spec = importlib.util.spec_from_file_location("mutate", _MUTATE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mutate() -> types.ModuleType:
    return _load_mutate()


# -- split_argv / parse_args -------------------------------------------------------


def test_split_argv_splits_on_the_first_double_dash(mutate: types.ModuleType) -> None:
    own, pytest_args = mutate.split_argv(["a.py", "old", "new", "--", "-k", "foo"])
    assert own == ["a.py", "old", "new"]
    assert pytest_args == ["-k", "foo"]


def test_split_argv_raises_without_a_double_dash(mutate: types.ModuleType) -> None:
    with pytest.raises(mutate.MutateError, match="--"):
        mutate.split_argv(["a.py", "old", "new"])


def test_parse_args_reads_the_file_old_new_and_pytest_args(mutate: types.ModuleType) -> None:
    args = mutate.parse_args(["a.py", "old", "new", "--", "tests/test_x.py"])
    assert args.file == Path("a.py")
    assert (args.old, args.new) == ("old", "new")
    assert args.pytest_args == ("tests/test_x.py",)
    assert args.timeout_s == mutate.DEFAULT_TIMEOUT_S


def test_parse_args_reads_an_explicit_timeout(mutate: types.ModuleType) -> None:
    args = mutate.parse_args(["--timeout", "5", "a.py", "old", "new", "--", "t.py"])
    assert args.timeout_s == 5.0


def test_parse_args_skip_baseline_defaults_to_false(mutate: types.ModuleType) -> None:
    args = mutate.parse_args(["a.py", "old", "new", "--", "t.py"])
    assert args.skip_baseline is False


def test_parse_args_reads_skip_baseline(mutate: types.ModuleType) -> None:
    args = mutate.parse_args(["--skip-baseline", "a.py", "old", "new", "--", "t.py"])
    assert args.skip_baseline is True


def test_parse_args_raises_when_no_pytest_args_follow_the_double_dash(
    mutate: types.ModuleType,
) -> None:
    with pytest.raises(mutate.MutateError, match="no pytest arguments"):
        mutate.parse_args(["a.py", "old", "new", "--"])


def test_parse_args_raises_when_new_is_missing_and_batch_is_not_given(
    mutate: types.ModuleType,
) -> None:
    with pytest.raises(mutate.MutateError, match="file, old and new are required"):
        mutate.parse_args(["a.py", "old", "--", "t.py"])  # missing <new>


def test_parse_args_exits_2_on_an_unrecognized_flag(mutate: types.ModuleType) -> None:
    with pytest.raises(SystemExit) as excinfo:
        mutate.parse_args(["--nope", "a.py", "old", "new", "--", "t.py"])
    assert excinfo.value.code == 2


# -- check_single_occurrence / mutate_text -----------------------------------------


def test_check_single_occurrence_accepts_exactly_one(mutate: types.ModuleType) -> None:
    mutate.check_single_occurrence("one two three", "two")  # does not raise


@pytest.mark.parametrize(("text", "old"), [("no match here", "x"), ("dup dup", "dup")])
def test_check_single_occurrence_raises_unless_exactly_one(
    mutate: types.ModuleType, text: str, old: str
) -> None:
    with pytest.raises(mutate.MutateError, match=r"occurs \d+ time"):
        mutate.check_single_occurrence(text, old)


def test_mutate_text_replaces_only_the_first_occurrence(mutate: types.ModuleType) -> None:
    # apply_mutation only calls this after check_single_occurrence passed; replace(...,
    # 1) is exercised directly here in case a future duplicate slips past a caller.
    assert mutate.mutate_text("a-b-a", "a", "X") == "X-b-a"


# -- classify -------------------------------------------------------------------------


def test_classify_kills_only_on_pytest_exit_code_1(mutate: types.ModuleType) -> None:
    assert mutate.classify(1).kind == "KILLED"


def test_classify_survives_only_on_pytest_exit_code_0(mutate: types.ModuleType) -> None:
    assert mutate.classify(0).kind == "SURVIVED"


@pytest.mark.parametrize(
    "returncode",
    [2, 3, 4, 5, 42, None],
    ids=[
        "interrupted",
        "internal-error",
        "usage-error",
        "no-tests-collected",
        "unknown",
        "timeout",
    ],
)
def test_classify_is_invalid_for_every_other_exit_code_and_a_timeout(
    mutate: types.ModuleType, returncode: int | None
) -> None:
    # MD6 (docs/audits/2026-09-26-foundation.md): none of these prove a test failed, so
    # none may be counted as KILLED -- and none proves every test passed either.
    assert mutate.classify(returncode).kind == "INVALID"


@pytest.mark.parametrize(
    ("returncode", "phrase"),
    [
        (2, "interrupted"),
        (3, "internal error"),
        (4, "usage error"),
        (5, "no tests were collected"),
        (None, "timeout"),
    ],
)
def test_classify_invalid_detail_names_the_reason(
    mutate: types.ModuleType, returncode: int | None, phrase: str
) -> None:
    assert phrase in mutate.classify(returncode).detail


# -- run_mutation (hermetic: a fake pytest runner, no subprocess) ---------------------


def test_run_mutation_kills_and_restores_when_the_fake_run_fails(
    mutate: types.ModuleType, tmp_path: Path
) -> None:
    target = tmp_path / "code.py"
    target.write_text("value = 1\n")
    calls: list[tuple[tuple[str, ...], float]] = []

    def fake_run(pytest_args: Sequence[str], timeout_s: float) -> int:
        calls.append((tuple(pytest_args), timeout_s))
        return 1

    mutation = mutate.Mutation(target, "1", "2")
    outcome = mutate.run_mutation(
        mutation, ["tests/x.py"], timeout_s=5.0, run=fake_run, skip_baseline=True
    )

    assert outcome.kind == "KILLED"
    assert target.read_text() == "value = 1\n"  # restored even though it killed
    assert calls == [(("tests/x.py",), 5.0)]


@pytest.mark.parametrize(
    ("returncode", "kind"),
    [
        (0, "SURVIVED"),
        (2, "INVALID"),
        (3, "INVALID"),
        (4, "INVALID"),
        (5, "INVALID"),
        (None, "INVALID"),
    ],
    ids=["passed", "interrupted", "internal-error", "usage-error", "no-tests-collected", "timeout"],
)
def test_run_mutation_classifies_every_other_fake_exit_code_and_restores(
    mutate: types.ModuleType, tmp_path: Path, returncode: int | None, kind: str
) -> None:
    target = tmp_path / "code.py"
    target.write_text("value = 1\n")
    mutation = mutate.Mutation(target, "1", "2")

    outcome = mutate.run_mutation(
        mutation, ["tests/x.py"], timeout_s=5.0, run=lambda *_: returncode, skip_baseline=True
    )

    assert outcome.kind == kind
    assert target.read_text() == "value = 1\n"  # restored on every outcome


def test_run_mutation_raises_and_touches_nothing_when_old_is_not_exactly_one(
    mutate: types.ModuleType, tmp_path: Path
) -> None:
    target = tmp_path / "code.py"
    target.write_text("value = 1\n")
    mutation = mutate.Mutation(target, "missing", "2")

    def fake_run(*_args: object) -> int:
        pytest.fail("run_mutation must not run pytest when the mutation could not be applied")

    with pytest.raises(mutate.MutateError, match="occurs 0 time"):
        mutate.run_mutation(
            mutation, ["tests/x.py"], timeout_s=5.0, run=fake_run, skip_baseline=True
        )

    assert target.read_text() == "value = 1\n"


# -- run_mutation's baseline check (increment 2) ---------------------------------------


def test_run_mutation_checks_a_green_baseline_before_mutating(
    mutate: types.ModuleType, tmp_path: Path
) -> None:
    target = tmp_path / "code.py"
    target.write_text("value = 1\n")
    mutation = mutate.Mutation(target, "1", "2")
    returncodes = iter([0, 1])  # baseline green, then the mutated run fails

    def fake_run(*_args: object) -> int:
        return next(returncodes)

    outcome = mutate.run_mutation(mutation, ["tests/x.py"], timeout_s=5.0, run=fake_run)

    assert outcome.kind == "KILLED"
    assert target.read_text() == "value = 1\n"


def test_run_mutation_is_invalid_and_never_mutates_when_the_baseline_is_not_green(
    mutate: types.ModuleType, tmp_path: Path
) -> None:
    target = tmp_path / "code.py"
    original = "value = 1\n"
    target.write_text(original)
    mutation = mutate.Mutation(target, "1", "2")
    calls: list[tuple[Sequence[str], float]] = []

    def fake_run(pytest_args: Sequence[str], timeout_s: float) -> int:
        calls.append((pytest_args, timeout_s))
        return 4  # a mistyped path: not green

    outcome = mutate.run_mutation(mutation, ["tests/x.py"], timeout_s=5.0, run=fake_run)

    assert outcome.kind == "INVALID"
    assert "not green before mutating" in outcome.detail
    assert target.read_text() == original  # never touched
    assert not mutate.backup_path(target).exists()  # never even backed up
    assert len(calls) == 1  # only the baseline ran; the mutation itself was never tried


def test_run_mutation_skip_baseline_runs_pytest_only_once(
    mutate: types.ModuleType, tmp_path: Path
) -> None:
    target = tmp_path / "code.py"
    target.write_text("value = 1\n")
    mutation = mutate.Mutation(target, "1", "2")
    calls: list[tuple[Sequence[str], float]] = []

    def fake_run(pytest_args: Sequence[str], timeout_s: float) -> int:
        calls.append((pytest_args, timeout_s))
        return 1

    outcome = mutate.run_mutation(
        mutation, ["tests/x.py"], timeout_s=5.0, run=fake_run, skip_baseline=True
    )

    assert outcome.kind == "KILLED"
    assert len(calls) == 1


# -- apply_mutation / restore (real files, no subprocess) --------------------------


def test_apply_mutation_backs_up_then_writes_the_mutation(
    mutate: types.ModuleType, tmp_path: Path
) -> None:
    target = tmp_path / "code.py"
    target.write_text("value = 1\n")
    backup = mutate.backup_path(target)

    mutate.apply_mutation(target, backup, "1", "2")

    assert target.read_text() == "value = 2\n"
    assert backup.read_text() == "value = 1\n"


def test_apply_mutation_raises_and_writes_nothing_when_old_is_not_exactly_one(
    mutate: types.ModuleType, tmp_path: Path
) -> None:
    target = tmp_path / "code.py"
    target.write_text("value = 1\n")
    backup = mutate.backup_path(target)

    with pytest.raises(mutate.MutateError, match="occurs 0 time"):
        mutate.apply_mutation(target, backup, "missing", "2")

    assert target.read_text() == "value = 1\n"
    assert not backup.exists()


def test_apply_mutation_refuses_when_a_backup_already_exists(
    mutate: types.ModuleType, tmp_path: Path
) -> None:
    target = tmp_path / "code.py"
    target.write_text("value = 1\n")
    backup = mutate.backup_path(target)
    backup.write_text("value = 0\n")  # a previous run's leftover

    with pytest.raises(mutate.MutateError, match="already exists"):
        mutate.apply_mutation(target, backup, "1", "2")

    assert target.read_text() == "value = 1\n"  # untouched
    assert backup.read_text() == "value = 0\n"  # untouched


def test_restore_writes_back_the_backup_and_removes_it(
    mutate: types.ModuleType, tmp_path: Path
) -> None:
    target = tmp_path / "code.py"
    target.write_text("value = 2\n")  # currently mutated
    backup = mutate.backup_path(target)
    backup.write_text("value = 1\n")

    mutate.restore(target, backup)

    assert target.read_text() == "value = 1\n"
    assert not backup.exists()


def test_apply_mutation_then_restore_round_trips_the_original_content(
    mutate: types.ModuleType, tmp_path: Path
) -> None:
    target = tmp_path / "code.py"
    original = "if x == 1:\n    return True\n"
    target.write_text(original)
    backup = mutate.backup_path(target)

    mutate.apply_mutation(target, backup, "== 1", "!= 1")
    assert target.read_text() != original

    mutate.restore(target, backup)
    assert target.read_text() == original


# -- restore's sha256 verification (increment 3) ---------------------------------------


def test_restore_raises_and_keeps_the_backup_when_the_write_does_not_verify(
    mutate: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "code.py"
    target.write_text("mutated\n")
    backup = mutate.backup_path(target)
    backup.write_text("original\n")
    digests = iter(["expected-digest", "different-digest"])
    monkeypatch.setattr(mutate, "sha256_of", lambda data: next(digests))  # noqa: ARG005

    with pytest.raises(mutate.MutateError, match="sha256"):
        mutate.restore(target, backup)

    assert backup.exists()  # kept, deliberately, for inspection
    assert target.read_text() == "original\n"  # the write itself still happened


def test_sha256_of_matches_for_equal_bytes_and_differs_for_different_bytes(
    mutate: types.ModuleType,
) -> None:
    assert mutate.sha256_of(b"same") == mutate.sha256_of(b"same")
    assert mutate.sha256_of(b"same") != mutate.sha256_of(b"different")


# -- run_pytest's environment (increment 3) ---------------------------------------------


def test_run_pytest_sets_pythondontwritebytecode(
    mutate: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured_argv: list[str] = []
    captured_env: dict[str, str] = {}

    def fake_subprocess_run(
        argv: list[str],
        *,
        env: dict[str, str],
        timeout: object,  # noqa: ARG001
        check: object,  # noqa: ARG001
    ) -> object:
        captured_argv[:] = argv
        captured_env.update(env)

        class _Result:
            returncode = 0

        return _Result()

    monkeypatch.setattr(mutate.subprocess, "run", fake_subprocess_run)
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)

    returncode = mutate.run_pytest("uv", ["tests/x.py"], timeout_s=5.0)

    assert returncode == 0
    assert captured_env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert captured_argv == ["uv", "run", "pytest", "tests/x.py"]


# -- parse_args: --batch / --jobs (increment 4) ----------------------------------------


def test_parse_args_reads_batch_mode(mutate: types.ModuleType, tmp_path: Path) -> None:
    spec = tmp_path / "spec.json"
    args = mutate.parse_args(["--batch", str(spec), "--", "t.py"])
    assert isinstance(args, mutate.BatchArgs)
    assert args.spec == spec
    assert args.jobs == 1
    assert args.skip_baseline is False


def test_parse_args_reads_jobs(mutate: types.ModuleType, tmp_path: Path) -> None:
    spec = tmp_path / "spec.json"
    args = mutate.parse_args(["--batch", str(spec), "--jobs", "4", "--", "t.py"])
    assert args.jobs == 4


def test_parse_args_raises_when_batch_is_combined_with_file_old_new(
    mutate: types.ModuleType, tmp_path: Path
) -> None:
    spec = tmp_path / "spec.json"
    with pytest.raises(mutate.MutateError, match="cannot be combined"):
        mutate.parse_args(["--batch", str(spec), "a.py", "old", "new", "--", "t.py"])


def test_parse_args_raises_when_jobs_is_less_than_1(
    mutate: types.ModuleType, tmp_path: Path
) -> None:
    spec = tmp_path / "spec.json"
    with pytest.raises(mutate.MutateError, match="--jobs must be at least 1"):
        mutate.parse_args(["--batch", str(spec), "--jobs", "0", "--", "t.py"])


def test_parse_args_raises_when_jobs_is_given_without_batch(mutate: types.ModuleType) -> None:
    with pytest.raises(mutate.MutateError, match="--jobs only applies with --batch"):
        mutate.parse_args(["--jobs", "2", "a.py", "old", "new", "--", "t.py"])


# -- parse_batch_spec --------------------------------------------------------------------


def test_parse_batch_spec_reads_file_old_new_and_defaults_id_to_position(
    mutate: types.ModuleType, tmp_path: Path
) -> None:
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps([{"file": "a.py", "old": "1", "new": "2"}]))

    specs = mutate.parse_batch_spec(spec)

    assert specs == [mutate.MutationSpec(id="1", file="a.py", old="1", new="2")]


def test_parse_batch_spec_reads_an_explicit_id(mutate: types.ModuleType, tmp_path: Path) -> None:
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps([{"file": "a.py", "old": "1", "new": "2", "id": "m1"}]))

    specs = mutate.parse_batch_spec(spec)

    assert specs[0].id == "m1"


def test_parse_batch_spec_raises_on_a_missing_file(
    mutate: types.ModuleType, tmp_path: Path
) -> None:
    with pytest.raises(mutate.MutateError, match="cannot read"):
        mutate.parse_batch_spec(tmp_path / "missing.json")


def test_parse_batch_spec_raises_on_invalid_json(mutate: types.ModuleType, tmp_path: Path) -> None:
    spec = tmp_path / "spec.json"
    spec.write_text("not json")

    with pytest.raises(mutate.MutateError, match="not valid JSON"):
        mutate.parse_batch_spec(spec)


@pytest.mark.parametrize("raw", ["{}", "[]", "null", '"a string"'])
def test_parse_batch_spec_raises_unless_a_non_empty_list(
    mutate: types.ModuleType, tmp_path: Path, raw: str
) -> None:
    spec = tmp_path / "spec.json"
    spec.write_text(raw)

    with pytest.raises(mutate.MutateError, match="non-empty JSON list"):
        mutate.parse_batch_spec(spec)


def test_parse_batch_spec_raises_when_an_entry_is_not_an_object(
    mutate: types.ModuleType, tmp_path: Path
) -> None:
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps(["not an object"]))

    with pytest.raises(mutate.MutateError, match=r"\[0\]: expected an object"):
        mutate.parse_batch_spec(spec)


@pytest.mark.parametrize("missing", ["file", "old", "new"])
def test_parse_batch_spec_raises_when_a_required_field_is_missing(
    mutate: types.ModuleType, tmp_path: Path, missing: str
) -> None:
    entry = {"file": "a.py", "old": "1", "new": "2"}
    del entry[missing]
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps([entry]))

    with pytest.raises(mutate.MutateError, match="must all be strings"):
        mutate.parse_batch_spec(spec)


def test_parse_batch_spec_raises_on_a_non_string_id(
    mutate: types.ModuleType, tmp_path: Path
) -> None:
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps([{"file": "a.py", "old": "1", "new": "2", "id": 1}]))

    with pytest.raises(mutate.MutateError, match="'id' must be a string"):
        mutate.parse_batch_spec(spec)


def test_parse_batch_spec_raises_on_a_duplicate_id(
    mutate: types.ModuleType, tmp_path: Path
) -> None:
    entry = {"file": "a.py", "old": "1", "new": "2", "id": "dup"}
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps([entry, entry]))

    with pytest.raises(mutate.MutateError, match="duplicate mutation id"):
        mutate.parse_batch_spec(spec)


# -- make_copy (a real, throwaway git repo under tmp_path; no network) -----------------


def _git(*args: str, cwd: Path) -> None:
    # Hermetic git: drop every GIT_* variable (under `git rebase -x`, GIT_DIR points at
    # the real repository, so a test's `git init/config/commit` would write into it), and
    # pass the identity per command instead of writing any config.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test", *args],  # noqa: S607
        cwd=cwd,
        env=env,
        check=True,
    )


def _init_repo(root: Path) -> None:
    _git("init", "-q", cwd=root)


def test_make_copy_copies_tracked_files_including_uncommitted_edits(
    mutate: types.ModuleType, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "a.py").write_text("original\n")
    (repo / "sub").mkdir()
    (repo / "sub" / "b.py").write_text("nested\n")
    _git("add", "a.py", "sub/b.py", cwd=repo)
    _git("commit", "-q", "-m", "initial", cwd=repo)
    (repo / "a.py").write_text("edited\n")  # uncommitted
    (repo / "untracked.py").write_text("never added\n")

    dest = tmp_path / "copy"
    mutate.make_copy(repo, dest)

    assert (dest / "a.py").read_text() == "edited\n"  # the uncommitted edit was copied
    assert (dest / "sub" / "b.py").read_text() == "nested\n"
    assert not (dest / "untracked.py").exists()  # never git add-ed: not copied
    assert (repo / "untracked.py").exists()  # the original repo itself is untouched


def test_make_copy_ignores_a_git_dir_inherited_from_the_environment(
    mutate: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Under `git rebase -x`, GIT_DIR names the rebasing repository; make_copy must still
    # copy `repo_root`, not whatever GIT_DIR points at.
    other = tmp_path / "other"
    other.mkdir()
    _init_repo(other)
    (other / "elsewhere.py").write_text("wrong repo\n")
    _git("add", "elsewhere.py", cwd=other)
    _git("commit", "-q", "-m", "other", cwd=other)
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "a.py").write_text("right repo\n")
    _git("add", "a.py", cwd=repo)
    _git("commit", "-q", "-m", "initial", cwd=repo)
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))

    dest = tmp_path / "copy"
    mutate.make_copy(repo, dest)

    assert (dest / "a.py").read_text() == "right repo\n"
    assert not (dest / "elsewhere.py").exists()


def test_make_copy_skips_a_tracked_file_deleted_in_the_working_tree(
    mutate: types.ModuleType, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "a.py").write_text("original\n")
    _git("add", "a.py", cwd=repo)
    _git("commit", "-q", "-m", "initial", cwd=repo)
    (repo / "a.py").unlink()

    dest = tmp_path / "copy"
    mutate.make_copy(repo, dest)

    assert not (dest / "a.py").exists()


# -- run_pytest_in_copy's environment ----------------------------------------------------


def test_run_pytest_in_copy_sets_uv_project_environment_and_pythonpath(
    mutate: types.ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured_argv: list[str] = []
    captured_env: dict[str, str] = {}
    captured_cwd: list[object] = []

    def fake_subprocess_run(
        argv: list[str],
        *,
        cwd: object,
        env: dict[str, str],
        timeout: object,  # noqa: ARG001
        check: object,  # noqa: ARG001
    ) -> object:
        captured_argv[:] = argv
        captured_env.update(env)
        captured_cwd.append(cwd)

        class _Result:
            returncode = 1

        return _Result()

    monkeypatch.setattr(mutate.subprocess, "run", fake_subprocess_run)
    venv = tmp_path / ".venv"
    copy_root = tmp_path / "copy"

    returncode = mutate.run_pytest_in_copy("uv", venv, copy_root, ["tests/x.py"], timeout_s=5.0)

    assert returncode == 1
    assert captured_argv == ["uv", "run", "--no-sync", "pytest", "tests/x.py"]
    assert captured_env["UV_PROJECT_ENVIRONMENT"] == str(venv)
    assert captured_env["PYTHONPATH"] == str(copy_root / "src")
    assert captured_env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert captured_cwd == [copy_root]


# -- run_one_batch_mutation / run_batch (hermetic: fake make_copy and run_in_copy) ------


def test_run_one_batch_mutation_kills_using_the_copys_own_mutated_code(
    mutate: types.ModuleType, tmp_path: Path
) -> None:
    def fake_make_copy(_repo_root: Path, dest: Path) -> None:
        dest.mkdir(parents=True)
        (dest / "a.py").write_text("value = 1\n")

    copy_roots: list[Path] = []

    def fake_run_in_copy(copy_root: Path, _pytest_args: Sequence[str], _timeout_s: float) -> int:
        copy_roots.append(copy_root)
        assert (copy_root / "a.py").read_text() == "value = 2\n"  # the mutation applied
        return 1

    spec = mutate.MutationSpec(id="m1", file="a.py", old="1", new="2")
    options = mutate.BatchOptions(
        pytest_args=("tests/x.py",), timeout_s=5.0, jobs=1, skip_baseline=True
    )

    result = mutate.run_one_batch_mutation(
        tmp_path / "repo", spec, options, make_copy=fake_make_copy, run_in_copy=fake_run_in_copy
    )

    assert result.id == "m1"
    assert result.outcome.kind == "KILLED"
    assert len(copy_roots) == 1
    assert not copy_roots[0].exists()  # the copy is removed afterwards


def test_run_one_batch_mutation_is_invalid_when_the_file_is_missing(
    mutate: types.ModuleType, tmp_path: Path
) -> None:
    def fake_make_copy(_repo_root: Path, dest: Path) -> None:
        dest.mkdir(parents=True)

    def fake_run_in_copy(*_args: object) -> int:
        pytest.fail("must not run pytest when the target file is missing")

    spec = mutate.MutationSpec(id="m1", file="missing.py", old="1", new="2")
    options = mutate.BatchOptions(pytest_args=("t.py",), timeout_s=5.0, jobs=1, skip_baseline=True)

    result = mutate.run_one_batch_mutation(
        tmp_path / "repo", spec, options, make_copy=fake_make_copy, run_in_copy=fake_run_in_copy
    )

    assert result.outcome.kind == "INVALID"
    assert "missing.py" in result.outcome.detail


def test_run_one_batch_mutation_is_invalid_when_old_is_not_exactly_one(
    mutate: types.ModuleType, tmp_path: Path
) -> None:
    def fake_make_copy(_repo_root: Path, dest: Path) -> None:
        dest.mkdir(parents=True)
        (dest / "a.py").write_text("value = 1\n")

    def fake_run_in_copy(*_args: object) -> int:
        pytest.fail("must not run pytest when the mutation could not be applied")

    spec = mutate.MutationSpec(id="m1", file="a.py", old="missing", new="2")
    options = mutate.BatchOptions(pytest_args=("t.py",), timeout_s=5.0, jobs=1, skip_baseline=True)

    result = mutate.run_one_batch_mutation(
        tmp_path / "repo", spec, options, make_copy=fake_make_copy, run_in_copy=fake_run_in_copy
    )

    assert result.outcome.kind == "INVALID"
    assert "occurs 0 time" in result.outcome.detail


def test_run_batch_is_invalid_and_runs_no_mutation_when_the_baseline_is_not_green(
    mutate: types.ModuleType, tmp_path: Path
) -> None:
    copy_roots: list[Path] = []

    def fake_make_copy(_repo_root: Path, dest: Path) -> None:
        copy_roots.append(dest)
        dest.mkdir(parents=True)

    run_roots: list[Path] = []

    def fake_run_in_copy(copy_root: Path, _pytest_args: Sequence[str], _timeout_s: float) -> int:
        run_roots.append(copy_root)
        return 4  # not green

    specs = [mutate.MutationSpec(id="m1", file="a.py", old="1", new="2")]
    options = mutate.BatchOptions(pytest_args=("t.py",), timeout_s=5.0, jobs=1, skip_baseline=False)

    result = mutate.run_batch(
        tmp_path / "repo", specs, options, make_copy=fake_make_copy, run_in_copy=fake_run_in_copy
    )

    assert isinstance(result, mutate.Outcome)
    assert result.kind == "INVALID"
    assert "not green before mutating" in result.detail
    assert len(copy_roots) == 1  # only the one baseline copy was made
    assert len(run_roots) == 1  # only the baseline ran; no mutation was attempted
    assert not copy_roots[0].exists()  # the baseline copy is removed afterwards


def test_run_batch_runs_every_mutation_and_returns_results_in_spec_order(
    mutate: types.ModuleType, tmp_path: Path
) -> None:
    def fake_make_copy(_repo_root: Path, dest: Path) -> None:
        dest.mkdir(parents=True)
        (dest / "a.py").write_text("value = 1\n")

    def fake_run_in_copy(copy_root: Path, _pytest_args: Sequence[str], _timeout_s: float) -> int:
        mutated = (copy_root / "a.py").read_text()
        return 1 if mutated == "value = 2\n" else 0  # only the real mutation kills

    specs = [
        mutate.MutationSpec(id="a", file="a.py", old="1", new="2"),  # a real mutation
        mutate.MutationSpec(id="b", file="a.py", old="1", new="1"),  # a no-op mutation
    ]
    options = mutate.BatchOptions(pytest_args=("t.py",), timeout_s=5.0, jobs=2, skip_baseline=True)

    results = mutate.run_batch(
        tmp_path / "repo", specs, options, make_copy=fake_make_copy, run_in_copy=fake_run_in_copy
    )

    assert isinstance(results, list)
    assert [result.id for result in results] == ["a", "b"]  # spec order, despite jobs=2
    assert results[0].outcome.kind == "KILLED"
    assert results[1].outcome.kind == "SURVIVED"


# -- print_batch_report ------------------------------------------------------------------


def testprint_batch_report_prints_one_line_per_mutation_and_a_summary(
    mutate: types.ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    results = [
        mutate.MutationResult("a", mutate.Outcome("KILLED", "killed detail")),
        mutate.MutationResult("b", mutate.Outcome("SURVIVED", "survived detail")),
    ]

    exit_code = mutate.print_batch_report(results)

    out = capsys.readouterr().out
    assert "a KILLED: killed detail" in out
    assert "b SURVIVED: survived detail" in out
    assert "2 mutation(s): 1 KILLED, 1 SURVIVED" in out
    assert exit_code == 1


def testprint_batch_report_exits_0_when_everything_was_killed(mutate: types.ModuleType) -> None:
    results = [mutate.MutationResult("a", mutate.Outcome("KILLED", "x"))]
    assert mutate.print_batch_report(results) == 0
