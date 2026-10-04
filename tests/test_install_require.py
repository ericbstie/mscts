"""install.require: a missing Installation is never installed without saying so (ADR-0008 §2)."""

import datetime
import io
import json
from pathlib import Path
from typing import override

import pytest
from support.pumpkin import FakeGitHub, fake_pumpkin

from mscts import install
from mscts.adapters.base import ProvisionError
from mscts.adapters.pumpkin import NIGHTLY_URL, TAGS_URL, PumpkinAdapter
from mscts.install import Terminal, install_from, install_release, require
from mscts.target import TARGET

ADAPTER = PumpkinAdapter()


def root_of(cache: Path) -> Path:
    return cache / "pumpkin/26.3"


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


def ask(typed: str) -> tuple[Terminal, io.StringIO]:
    shown = io.StringIO()
    return Terminal(stdin=Keyboard(typed), stdout=shown), shown


QUESTION = (
    "pumpkin 26.3 is not installed. Download its latest build (Y) or provision it yourself (N)? "
)
FROM = "`mscts adapter install pumpkin --from <file>`"


def test_an_installed_installation_is_returned_without_asking(tmp_path: Path) -> None:
    done = install_release(ADAPTER, TARGET, tmp_path, None, FakeGitHub())
    terminal, shown = ask("")
    github = FakeGitHub()
    assert require(ADAPTER, TARGET, tmp_path, terminal=terminal, fetch=github) == (
        done.installation
    )
    assert (github.fetched, shown.getvalue()) == ([], "")


def test_a_from_installation_is_used_as_it_is(tmp_path: Path) -> None:
    supplied = tmp_path / "pumpkin"
    supplied.write_bytes(fake_pumpkin(tail=b"my own build"))
    done = install_from(ADAPTER, TARGET, tmp_path / "cache", supplied)
    github = FakeGitHub()
    assert require(ADAPTER, TARGET, tmp_path / "cache", fetch=github) == done.installation
    assert github.fetched == []


def test_yes_downloads_the_latest_build_and_says_so(tmp_path: Path) -> None:
    terminal, shown = ask("y\n")
    github = FakeGitHub()
    installation = require(ADAPTER, TARGET, tmp_path, terminal=terminal, fetch=github)
    assert github.fetched == [TAGS_URL, NIGHTLY_URL]
    assert installation.root == root_of(tmp_path)
    assert shown.getvalue() == (
        f"{QUESTION}downloading {TAGS_URL} ...\ndownloading {NIGHTLY_URL} ...\n"
        f"installed pumpkin nightly 4426d11 from {NIGHTLY_URL} into {root_of(tmp_path)}\n"
    )


def test_yes_records_installed_at_from_the_supplied_clock(tmp_path: Path) -> None:
    terminal, _ = ask("y\n")
    moment = datetime.datetime(2001, 2, 3, 4, 5, 6, 123456, tzinfo=datetime.UTC)

    installation = require(
        ADAPTER, TARGET, tmp_path, terminal=terminal, fetch=FakeGitHub(), now=lambda: moment
    )

    assert installation.source is not None
    assert installation.source.installed_at == "2001-02-03T04:05:06+00:00"
    recorded = json.loads((installation.root / install.SOURCE).read_text())
    assert recorded["installed_at"] == installation.source.installed_at


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
        "unasked. Install its latest build with `mscts adapter install pumpkin`, "
        f"or provision it yourself with {FROM}"
    )
    assert github.fetched == []
    if terminal is not None:
        assert isinstance(terminal.stdout, io.StringIO)
        assert terminal.stdout.getvalue() == ""


def test_the_from_command_is_the_exact_command_line() -> None:
    assert f"`{install.install_command('pumpkin', path='<file>')}`" == FROM


def test_a_version_command_names_it_after_an_at() -> None:
    assert install.install_command("pumpkin", version="4426d11") == (
        "mscts adapter install pumpkin@4426d11"
    )
