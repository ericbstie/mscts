"""An Adapter author writes one folder, plus the one line in cli.py that registers it (#155)."""

import ast
import importlib
from pathlib import Path

import pytest

import mscts
from mscts.cli import ADAPTERS, REFERENCE

SRC = Path(mscts.__file__).parent
ADAPTERS_DIR = SRC / "adapters"
TESTS = Path(__file__).parent


@pytest.mark.parametrize("name", sorted(ADAPTERS))
def test_an_adapter_is_the_folder_named_for_it(name: str) -> None:
    adapter = ADAPTERS[name]()
    assert adapter.name == name
    module = importlib.import_module(type(adapter).__module__)
    assert module.__file__ is not None
    assert Path(module.__file__).parent == ADAPTERS_DIR / name


@pytest.mark.parametrize("name", sorted(ADAPTERS))
def test_an_adapters_tests_are_the_folder_named_for_it(name: str) -> None:
    assert sorted((TESTS / name).glob("test_*.py")) != []
    assert sorted(TESTS.glob(f"test_{name}_*.py")) == []


def test_no_adapter_data_sits_outside_its_folder() -> None:
    assert not (ADAPTERS_DIR / "data").exists()


def _modules_imported_by(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = [alias.name for n in ast.walk(tree) if isinstance(n, ast.Import) for alias in n.names]
    froms = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module]
    return imports + froms


def _adapters_imported_by(path: Path) -> set[str]:
    """The Adapter folders `path` imports from, by name."""
    prefix = "mscts.adapters."
    return {
        module.removeprefix(prefix).split(".")[0]
        for module in _modules_imported_by(path)
        if module.startswith(prefix)
    } & set(ADAPTERS)


def _own(path: Path) -> set[str]:
    """The Adapter whose folder `path` is in, if any."""
    return {path.relative_to(ADAPTERS_DIR).parts[0]} if path.is_relative_to(ADAPTERS_DIR) else set()


def test_outside_its_folder_only_cli_names_an_adapter_and_regen_the_reference() -> None:
    allowed = {SRC / "cli.py": set(ADAPTERS), SRC / "codec" / "regen.py": {REFERENCE}}
    for path in sorted(SRC.rglob("*.py")):
        others = _adapters_imported_by(path) - _own(path) - allowed.get(path, set())
        assert others == set(), f"{path} imports the {sorted(others)} Adapter"
