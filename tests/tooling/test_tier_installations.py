"""A live tier stops before its first test when its Installation is missing, naming the fix."""

from pathlib import Path

from support.tiers import missing_installations

from mscts import install
from mscts.adapters.vanilla import VanillaAdapter
from mscts.target import TARGET
from tests.adapters.test_vanilla_install import ENTRY, PINNED, FakeMojang


def test_the_reference_tier_without_vanilla_names_its_install_command(tmp_path: Path) -> None:
    (problem,) = missing_installations({"reference"}, tmp_path)
    assert problem.startswith("vanilla 26.3 is not installed")
    assert "`mscts adapter install vanilla`" in problem
    assert list(tmp_path.iterdir()) == []  # nothing downloaded


def test_the_candidate_tier_without_pumpkin_names_its_install_command(tmp_path: Path) -> None:
    (problem,) = missing_installations({"candidate"}, tmp_path)
    assert "`mscts adapter install pumpkin --from <file>`" in problem


def test_the_unit_tier_needs_nothing(tmp_path: Path) -> None:
    assert missing_installations(set(), tmp_path) == []


def test_an_installed_reference_is_no_problem(tmp_path: Path) -> None:
    install.install_entry(VanillaAdapter(), TARGET, tmp_path, ENTRY, FakeMojang(PINNED))
    assert missing_installations({"reference", "statistical"}, tmp_path) == []
