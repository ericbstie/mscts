"""scripts/mutate.py's pure and filesystem parts, hermetic (no subprocess, no pytest run)."""

import importlib.util
import types
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


# -- verdict ------------------------------------------------------------------------


@pytest.mark.parametrize(("returncode", "expected"), [(1, 0), (2, 0), (None, 0), (0, 1)], ids=str)
def test_verdict_is_0_iff_the_tests_failed_or_timed_out(
    mutate: types.ModuleType, returncode: int | None, expected: int
) -> None:
    assert mutate.verdict(returncode) == expected


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
