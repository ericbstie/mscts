#!/usr/bin/env python3
"""Check public top-level definitions against docs/PLAN.md (#4)."""

import ast
import re
import sys
from pathlib import Path


def public_names(source: Path) -> dict[str, set[str]]:
    """List definitions and assignment targets, excluding imports and private names."""
    modules: dict[str, set[str]] = {}
    for path in sorted(source.rglob("*.py")):
        names: set[str] = set()
        for node in ast.parse(path.read_text(), filename=str(path)).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    names.update(
                        part.id
                        for part in ast.walk(target)
                        if isinstance(part, ast.Name) and isinstance(part.ctx, ast.Store)
                    )
            elif isinstance(node, (ast.AnnAssign, ast.TypeAlias)):
                target = node.target if isinstance(node, ast.AnnAssign) else node.name
                if isinstance(target, ast.Name):
                    names.add(target.id)
        relative = path.relative_to(source).with_suffix("")
        parts = relative.parts[:-1] if relative.name == "__init__" else relative.parts
        module = ".".join(parts) or source.name
        modules[module] = {name for name in names if not name.startswith("_")}
    return modules


def check_names(source: Path, plan: Path) -> int:
    """Print each module:name missing from PLAN and return 1 if any are missing."""
    documented = set(re.findall(r"\b\w+\b", plan.read_text()))
    missing = [
        f"{module}:{name}"
        for module, names in public_names(source).items()
        for name in sorted(names - documented)
    ]
    for name in missing:
        print(name)
    return int(bool(missing))


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    sys.exit(check_names(root / "src" / "mscts", root / "docs" / "PLAN.md"))
