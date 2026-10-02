"""Public definitions must be named in PLAN (#4)."""

import importlib.util
import subprocess
import sys
import tomllib
import types
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "plan_names.py"


def _load_plan_names() -> types.ModuleType:
    assert _SCRIPT.is_file(), "the PLAN name check has not been implemented"
    spec = importlib.util.spec_from_file_location("plan_names", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_public_name_fails_with_module_and_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan_names = _load_plan_names()
    source = tmp_path / "src" / "mscts"
    source.mkdir(parents=True)
    (source / "sample.py").write_text("def documented(): pass\ndef missing(): pass\n")
    plan = tmp_path / "PLAN.md"
    plan.write_text("`documented` and `missing_suffix`\n")

    assert plan_names.check_names(source, plan) == 1
    assert capsys.readouterr().out == "sample:missing\n"


def test_documented_public_names_pass_silently(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "sample.py").write_text("class Public: pass\nLIMIT: int = 1\n")
    plan = tmp_path / "PLAN.md"
    plan.write_text("`Public` and `LIMIT`\n")

    assert _load_plan_names().check_names(source, plan) == 0
    assert capsys.readouterr().out == ""


def test_ast_scan_covers_definitions_constants_and_type_aliases(tmp_path: Path) -> None:
    (tmp_path / "sample.py").write_text(
        "class Public:\n"
        "    field = 1\n"
        "    def method(self): pass\n"
        "def function():\n"
        "    local = 1\n"
        "async def coroutine(): pass\n"
        "CONSTANT = 1\n"
        "ANNOTATED: int = 2\n"
        "FIRST = SECOND = 3\n"
        "LEFT, *REST = [1, 2]\n"
        "type Alias = str | int\n"
        "external.field = 1\n"
        "external[0] = 2\n"
        "from elsewhere import Imported\n"
    )
    assert _load_plan_names().public_names(tmp_path) == {
        "sample": {
            "Public",
            "function",
            "coroutine",
            "CONSTANT",
            "ANNOTATED",
            "FIRST",
            "SECOND",
            "LEFT",
            "REST",
            "Alias",
        }
    }


def test_underscore_prefixed_names_need_no_plan_entry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "sample.py").write_text(
        "class _Hidden: pass\ndef _helper(): pass\n_PRIVATE = 1\ntype _Alias = str\n__all__ = []\n"
    )
    plan = tmp_path / "PLAN.md"
    plan.write_text("")
    assert _load_plan_names().check_names(source, plan) == 0
    assert capsys.readouterr().out == ""


def test_missing_names_are_sorted_and_package_initializers_name_the_package(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "src"
    package = source / "package"
    package.mkdir(parents=True)
    (source / "z.py").write_text("ZED = 1\nALPHA = 2\n")
    (package / "__init__.py").write_text("def exported(): pass\n")
    (package / "child.py").write_text("def child(): pass\n")
    plan = tmp_path / "PLAN.md"
    plan.write_text("")
    assert _load_plan_names().check_names(source, plan) == 1
    assert capsys.readouterr().out == "package:exported\npackage.child:child\nz:ALPHA\nz:ZED\n"


@pytest.mark.parametrize("documented", [False, True], ids=["missing", "present"])
def test_script_exit_code_checks_the_plan_relative_to_itself(
    tmp_path: Path, *, documented: bool
) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "plan_names.py"
    script.write_bytes(_SCRIPT.read_bytes())
    source = tmp_path / "src" / "mscts"
    source.mkdir(parents=True)
    (source / "sample.py").write_text("class Public: pass\n")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "PLAN.md").write_text("Public" if documented else "")
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == (0 if documented else 1)
    assert result.stdout == ("" if documented else "sample:Public\n")
    assert result.stderr == ""


def test_mise_check_depends_on_the_plan_names_task() -> None:
    tasks = tomllib.loads((_SCRIPT.parent.parent / "mise.toml").read_text())["tasks"]
    assert "plan" in tasks["check"]["depends"]
    assert tasks["plan"]["run"] == "uv run python scripts/plan_names.py"
