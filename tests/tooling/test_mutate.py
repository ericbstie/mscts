"""scripts/mutate.py's pure and filesystem parts, hermetic (no subprocess, no pytest run)."""

import importlib.util
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


def test_parse_args_exits_2_on_a_bad_own_argument(mutate: types.ModuleType) -> None:
    with pytest.raises(SystemExit) as excinfo:
        mutate.parse_args(["a.py", "old", "--", "t.py"])  # missing <new>
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
