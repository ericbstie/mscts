"""The CLI reference covers the commands and options of today's help (#14)."""

import re
from pathlib import Path

import pytest

from mscts import cli

ROOT = Path(__file__).resolve().parents[2]


def test_every_command_and_option_in_help_is_documented(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLUMNS", "200")
    reference = (ROOT / "docs/reference/cli.md").read_text()
    sections = {
        match[1]: match[2]
        for match in re.finditer(
            r"^## `(mscts[^`]*?)`\n(.*?)(?=^## |\Z)", reference, re.MULTILINE | re.DOTALL
        )
    }
    pending: list[tuple[str, ...]] = [()]
    commands = set()
    while pending:
        command = pending.pop()
        name = " ".join(("mscts", *command))
        commands.add(name)
        with pytest.raises(SystemExit) as exited:
            cli.main([*command, "--help"])
        assert exited.value.code == 0
        help_text = capsys.readouterr().out
        assert name in sections, f"Missing command in cli.md: {name}"
        option_rows = help_text.split("\noptions:\n", 1)[1]
        options = set(re.findall(r"(?<!\w)--?[a-z][\w-]*", option_rows)) - {"-h", "--help"}
        signatures = re.findall(r"^mscts .+$", sections[name], re.MULTILINE)
        signatures.extend(re.findall(r"^\| `(-[^`]+)`", sections[name], re.MULTILINE))
        documented = set(re.findall(r"(?<!\w)--?[a-z][\w-]*", "\n".join(signatures)))
        assert options == documented, f"{name}: help {options}, docs {documented}"
        for children in re.findall(r"^  \{([^}]+)\}\n(?=    \w)", help_text, re.MULTILINE):
            pending.extend((*command, child) for child in children.split(","))
    assert commands == sections.keys()
    assert "-h" in reference
    assert "--help" in reference
