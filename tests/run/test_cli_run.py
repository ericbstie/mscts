"""`mscts run`: a Run of the Reference against a Candidate, with fake Adapters."""

import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from types import MappingProxyType

import pytest

from mscts import cli, install
from mscts.adapters.base import Adapter, Installation, ProvisionError
from mscts.target import Target
from tests.run.fakes import FakeAdapter

type Fakes = Callable[..., None]


@pytest.fixture
def fakes(run_token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Make `mscts run` use fake vanilla and pumpkin Adapters, installed unless told not."""
    monkeypatch.setenv("MSCTS_CACHE", str(tmp_path / "cache"))

    def use(pumpkin_description: str | None = None, *, installed: bool = True) -> None:
        adapters: Mapping[str, Callable[[], Adapter]] = MappingProxyType(
            {
                "vanilla": lambda: FakeAdapter("vanilla", run_token),
                "pumpkin": lambda: FakeAdapter(
                    "pumpkin", run_token, description=pumpkin_description
                ),
            }
        )
        monkeypatch.setattr(cli, "ADAPTERS", adapters)

        def require(adapter: Adapter, target: Target, cache: Path, **_: object) -> Installation:
            if not installed:
                msg = f"{adapter.name} is not installed: run `mscts adapter install {adapter.name}`"
                raise ProvisionError(msg)
            return Installation(adapter=adapter.name, target=target, root=cache / adapter.name)

        monkeypatch.setattr(install, "require", require)

    return use


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = cli.main(["run", *argv])
    out, err = capsys.readouterr()
    return code, out, err


def test_a_run_prints_the_report_and_says_what_it_does(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    fakes()

    code, out, err = _run(capsys, "--candidate", "pumpkin", "--repeat", "2")

    assert code == 0
    assert "No differences from vanilla were found in the 2 scenarios run." in out
    assert "Timings" in out
    assert "--out" in out  # the Report says what it leaves out
    assert "starting vanilla and pumpkin ..." in err
    assert "running status/basic" in err
    assert "running status/ping" in err
    assert "mscts Report" not in err


def test_a_run_with_divergences_still_exits_0(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    fakes(pumpkin_description="not vanilla")

    code, out, _ = _run(capsys, "--candidate", "pumpkin", "--repeat", "1")

    assert code == 0
    assert "Differences a player would notice" in out
    assert '"not vanilla"' in out


def test_the_scenario_glob_picks_scenarios_and_their_prerequisites(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    fakes()

    code, _, err = _run(
        capsys, "--candidate", "pumpkin", "--scenario", "status/p*", "--repeat", "1"
    )

    assert code == 0
    assert err.index("running status/basic") < err.index("running status/ping")


def test_a_glob_that_matches_nothing_fails_naming_the_scenarios(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    fakes()

    code, out, err = _run(capsys, "--candidate", "pumpkin", "--scenario", "nothing/*")

    assert (code, out) == (1, "")
    assert err.startswith("mscts: ")
    assert err.count("\n") == 1
    assert "status/basic" in err


def test_a_missing_installation_fails_naming_the_install_command(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    fakes(installed=False)

    code, _, err = _run(capsys, "--candidate", "pumpkin")

    assert code == 1
    assert err.startswith("mscts: ")
    assert err.count("\n") == 1
    assert "mscts adapter install" in err


def test_the_work_directory_is_removed_afterwards(
    fakes: Fakes,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fakes()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()

    code, _, _ = _run(capsys, "--candidate", "pumpkin", "--repeat", "1")

    assert code == 0
    assert list((tmp_path / "tmp").iterdir()) == []
