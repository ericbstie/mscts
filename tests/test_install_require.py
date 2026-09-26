"""install.require: a missing Installation is never installed without saying so (ADR-0008 §2)."""

import io
from pathlib import Path
from typing import override

import pytest

from mscts import install, registry
from mscts.adapters.base import ProvisionError
from mscts.install import Terminal, install_entry, install_from, require
from mscts.registry import Registry
from mscts.target import TARGET
from tests.test_install import ADAPTER, ENTRY, REGISTRY, URL, FakeGitHub, root_of


class Keyboard(io.StringIO):
    """Stdin that is a TTY, typed in advance."""

    @override
    def isatty(self) -> bool:
        return True


class Unreadable(io.StringIO):
    """Stdin that is no TTY and must never be read."""

    @override
    def read(self, size: int | None = -1) -> str:
        raise AssertionError(size)

    @override
    def readline(self, size: int | None = -1) -> str:
        raise AssertionError(size)


@pytest.fixture(autouse=True)
def official(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "official", lambda: REGISTRY)


def ask(typed: str) -> tuple[Terminal, io.StringIO]:
    shown = io.StringIO()
    return Terminal(stdin=Keyboard(typed), stdout=shown), shown


QUESTION = (
    "pumpkin 26.3 is not installed. "
    "Download pumpkin nightly-test (Y) or provision it yourself (N)? "
)
FROM = "`mscts adapter install pumpkin --from <file>`"


def test_an_installed_installation_is_returned_without_asking(tmp_path: Path) -> None:
    done = install_entry(ADAPTER, TARGET, tmp_path, ENTRY, FakeGitHub())
    terminal, shown = ask("")
    github = FakeGitHub()
    assert require(ADAPTER, TARGET, tmp_path, terminal=terminal, fetch=github) == (
        done.installation
    )
    assert (github.fetched, shown.getvalue()) == ([], "")


def test_a_from_installation_is_used_as_it_is(tmp_path: Path) -> None:
    supplied = tmp_path / "pumpkin"
    supplied.write_bytes(b"\x7fELF my own build")
    done = install_from(ADAPTER, TARGET, tmp_path / "cache", supplied, REGISTRY)
    github = FakeGitHub()
    assert require(ADAPTER, TARGET, tmp_path / "cache", fetch=github) == done.installation
    assert github.fetched == []


def test_yes_downloads_the_entry_and_says_so(tmp_path: Path) -> None:
    terminal, shown = ask("y\n")
    github = FakeGitHub()
    installation = require(ADAPTER, TARGET, tmp_path, terminal=terminal, fetch=github)
    assert github.fetched == [URL]
    assert installation.root == root_of(tmp_path)
    assert shown.getvalue() == (
        f"{QUESTION}downloading {URL} ...\n"
        f"installed pumpkin nightly-test from {URL} into {root_of(tmp_path)}\n"
    )


def test_no_prints_the_from_command_and_refuses_naming_it(tmp_path: Path) -> None:
    terminal, shown = ask("N\n")
    github = FakeGitHub()
    with pytest.raises(ProvisionError) as raised:
        require(ADAPTER, TARGET, tmp_path, terminal=terminal, fetch=github)
    assert github.fetched == []
    assert shown.getvalue() == f"{QUESTION}Provision it yourself, then run {FROM}\n"
    assert FROM in str(raised.value)
    assert not root_of(tmp_path).exists()


def test_an_unexpected_answer_asks_again(tmp_path: Path) -> None:
    terminal, shown = ask("\nmaybe\nyes\n")
    require(ADAPTER, TARGET, tmp_path, terminal=terminal, fetch=FakeGitHub())
    again = "Please answer y or n. "
    assert shown.getvalue().startswith(f"{QUESTION}{again}{again}downloading")


def test_end_of_input_refuses_and_names_both_commands(tmp_path: Path) -> None:
    terminal, _ = ask("maybe\n")
    github = FakeGitHub()
    with pytest.raises(ProvisionError) as raised:
        require(ADAPTER, TARGET, tmp_path, terminal=terminal, fetch=github)
    assert "`mscts adapter install pumpkin`" in str(raised.value)
    assert FROM in str(raised.value)
    assert github.fetched == []


@pytest.mark.parametrize(
    "terminal",
    [None, Terminal(stdin=Unreadable(), stdout=io.StringIO())],
    ids=["no-terminal", "not-a-tty"],
)
def test_without_a_tty_it_fails_at_once_naming_both_commands(
    tmp_path: Path, terminal: Terminal | None
) -> None:
    github = FakeGitHub()
    with pytest.raises(ProvisionError) as raised:
        require(ADAPTER, TARGET, tmp_path, terminal=terminal, fetch=github)
    assert str(raised.value) == (
        "pumpkin 26.3 is not installed, and without a terminal nothing is installed "
        "unasked. Install pumpkin nightly-test with `mscts adapter install pumpkin`, "
        f"or provision it yourself with {FROM}"
    )
    assert github.fetched == []
    if terminal is not None:
        assert isinstance(terminal.stdout, io.StringIO)
        assert terminal.stdout.getvalue() == ""


def test_with_no_registry_entry_only_the_from_command_is_offered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(registry, "official", lambda: Registry(entries=()))
    terminal, shown = ask("y\n")
    with pytest.raises(ProvisionError) as raised:
        require(ADAPTER, TARGET, tmp_path, terminal=terminal, fetch=FakeGitHub())
    assert str(raised.value).startswith("pumpkin 26.3 is not installed, and no registry entry")
    assert str(raised.value).endswith(f"provision it yourself with {FROM}")
    assert shown.getvalue() == ""


def test_the_from_command_is_the_exact_command_line() -> None:
    assert f"`{install.install_command('pumpkin', path='<file>')}`" == FROM
