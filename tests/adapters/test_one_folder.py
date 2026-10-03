"""An Adapter author writes one folder, and two lines in cli.py: its import and entry (#155)."""

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


def test_adapters_holds_only_the_shared_modules_and_one_folder_per_adapter() -> None:
    loose = [
        entry.name
        for entry in ADAPTERS_DIR.iterdir()
        if entry.name != "__pycache__"
        and not (entry.is_file() and entry.suffix == ".py")
        and not (entry.is_dir() and entry.name in ADAPTERS)
    ]
    assert loose == []


def _names_in(tree: ast.AST, package: str) -> list[str]:
    """Every dotted name `tree`, a module of `package`, imports, and every string it holds."""
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = _absolute(node.module, node.level, package)
            names += [base] + [f"{base}.{alias.name}" for alias in node.names]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.append(node.value)
    return names


def _absolute(module: str | None, level: int, package: str) -> str:
    """The absolute name of `from <level dots><module> import ...` in `package`."""
    if level == 0:
        return module or ""
    parts = package.split(".")[: len(package.split(".")) - (level - 1)]
    return ".".join([*parts, module] if module else parts)


def _adapters_named_by(source: str, package: str) -> set[str]:
    """The Adapters that `source`, a module of `package`, imports or names, by name."""
    prefix = "mscts.adapters."
    return {
        name.removeprefix(prefix).split(".")[0]
        for name in _names_in(ast.parse(source), package)
        if name.startswith(prefix)
    } & set(ADAPTERS)


def _own(path: Path) -> set[str]:
    """The Adapter whose folder `path` is in, if any."""
    return {path.relative_to(ADAPTERS_DIR).parts[0]} if path.is_relative_to(ADAPTERS_DIR) else set()


def test_outside_its_folder_only_cli_names_an_adapter_and_regen_the_reference() -> None:
    allowed = {SRC / "cli.py": set(ADAPTERS), SRC / "codec" / "regen.py": {REFERENCE}}
    for path in sorted(SRC.rglob("*.py")):
        package = ".".join(path.parent.relative_to(SRC.parent).parts)
        named = _adapters_named_by(path.read_text(encoding="utf-8"), package)
        others = named - _own(path) - allowed.get(path, set())
        assert others == set(), f"{path} names the {sorted(others)} Adapter"


@pytest.mark.parametrize(
    ("source", "package"),
    [
        ("import mscts.adapters.pumpkin", "mscts"),
        ("from mscts.adapters.pumpkin import PumpkinAdapter", "mscts"),
        ("from mscts.adapters import pumpkin", "mscts"),
        ("from .adapters.pumpkin import PumpkinAdapter", "mscts"),
        ("from .adapters import pumpkin", "mscts"),
        ("from ..adapters import pumpkin", "mscts.codec"),
        ("from ..pumpkin import PumpkinAdapter", "mscts.adapters.vanilla"),
        ('importlib.import_module("mscts.adapters.pumpkin")', "mscts"),
    ],
)
def test_every_form_of_naming_an_adapter_is_caught(source: str, package: str) -> None:
    assert _adapters_named_by(source, package) == {"pumpkin"}


@pytest.mark.parametrize(
    "source",
    [
        "from mscts.adapters import base, fetch",
        "from .adapters.base import Build",
        "from . import pumpkin",  # mscts.pumpkin, not the Adapter
        '"pumpkin"',
    ],
)
def test_naming_no_adapter_is_not_caught(source: str) -> None:
    assert _adapters_named_by(source, "mscts") == set()
