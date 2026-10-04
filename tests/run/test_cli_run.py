"""`mscts run`: a Run of the Reference against a Candidate, with fake Adapters."""

import dataclasses
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from types import MappingProxyType

import pytest

from mscts import cli, install, report_json
from mscts import group as group_module
from mscts.adapters.base import Adapter, Installation, ProvisionError
from mscts.group import Group, GroupKind
from mscts.groups import status
from mscts.report import Report, render_markdown, render_text
from mscts.target import Target
from tests.run.fakes import FakeAdapter

type Fakes = Callable[..., None]

PING_AND_BASIC = "status/[bp]*"
"""The status Groups the fake servers answer: `status/with-player` needs a join."""


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

    code, out, err = _run(
        capsys, "--candidate", "pumpkin", "--group", PING_AND_BASIC, "--repeat", "2"
    )

    assert code == 0
    assert out.startswith("Running tests against pumpkin\n✓ status/basic/"), out
    assert "✗" not in out, out
    assert "\n11 passed, 0 failed. (100%)\nTook " in out, out
    assert err.index("starting vanilla and pumpkin ...") < err.index("running status/basic")
    assert "running status/ping" in err
    assert "mscts Report" not in err


def test_a_run_with_divergences_still_exits_0(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    fakes(pumpkin_description="not vanilla")

    code, out, _ = _run(
        capsys, "--candidate", "pumpkin", "--group", PING_AND_BASIC, "--repeat", "1"
    )

    assert code == 0
    assert out.startswith(
        "Running tests against pumpkin\n✗ status/basic/status_response.description.text\n"
    ), out
    assert "\n9 passed, 2 failed. (81.8%)\n" in out, out


def test_the_cli_measures_the_total_run_time(
    fakes: Fakes, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes()
    times = iter((10.0, 51.25))
    monkeypatch.setattr(cli, "perf_counter", lambda: next(times))

    code, out, _ = _run(
        capsys, "--candidate", "pumpkin", "--group", PING_AND_BASIC, "--repeat", "1"
    )

    assert code == 0
    assert out.endswith("\nTook 41.2 s\n"), out


def test_the_group_glob_picks_the_groups(fakes: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    fakes()

    code, _, err = _run(capsys, "--candidate", "pumpkin", "--group", "status/p*", "--repeat", "1")

    assert code == 0
    assert "running status/ping" in err
    assert "running status/basic" not in err


def test_the_group_flag_selects_the_status_groups(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    fakes()

    code, _, err = _run(capsys, "--candidate", "pumpkin", "--group", "status/*", "--repeat", "1")

    assert code == 0
    assert "running status/basic" in err
    assert "running status/ping" in err


def test_the_group_flag_selects_a_tick_exact_group_too(
    fakes: Fakes, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes()
    tick_exact = Group(id="test/ticks", run=status.basic, kind=GroupKind.TICK_EXACT)
    monkeypatch.setitem(group_module._REGISTERED, tick_exact.id, tick_exact)  # noqa: SLF001

    code, _, err = _run(capsys, "--candidate", "pumpkin", "--group", "test/*", "--repeat", "1")

    assert code == 0, err
    assert "running test/ticks" in err


def test_the_scenario_flag_is_gone(fakes: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    fakes()

    with pytest.raises(SystemExit) as exited:
        cli.main(["run", "--candidate", "pumpkin", "--scenario", "status/*", "--repeat", "1"])

    assert exited.value.code == 2
    assert "unrecognized arguments: --scenario" in capsys.readouterr().err


def test_a_glob_that_matches_nothing_fails_naming_the_groups(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    fakes()

    code, out, err = _run(capsys, "--candidate", "pumpkin", "--group", "nothing/*")

    assert (code, out) == (1, "")
    assert err.startswith("mscts: ")
    assert err.count("\n") == 1
    assert "no registered exact or tick-exact Group matches --group 'nothing/*'" in err
    assert "status/basic" in err


def test_the_help_speaks_of_groups(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLUMNS", "200")  # argparse wraps its help to the terminal width

    for argv in (["--help"], ["run", "--help"]):
        with pytest.raises(SystemExit) as exited:
            cli.main(argv)
        assert exited.value.code == 0
    out = capsys.readouterr().out

    assert "play Groups against vanilla and a Candidate, and print the Report" in out
    assert "--group GLOB" in out
    assert "the Group ids to play, prerequisites added (default: status/*)" in out
    assert "how many times to play each Group (default: 5)" in out
    assert "scenario" not in out.lower()


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

    code, _, _ = _run(capsys, "--candidate", "pumpkin", "--group", PING_AND_BASIC, "--repeat", "1")

    assert code == 0
    assert list((tmp_path / "tmp").iterdir()) == []


@pytest.mark.parametrize("option", ["-v", "--verbose"])
def test_verbose_cli_adds_header_values_and_group_times(
    option: str, fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        cli.main(["run", "--help"])
    help_text, _ = capsys.readouterr()
    assert option in help_text
    fakes(pumpkin_description="not vanilla")
    code, out, err = _run(capsys, "--candidate", "pumpkin", "--repeat", "1", option)
    assert code == 0, err
    assert '  vanilla sends "mscts", pumpkin sends "not vanilla"\n' in out, out
    assert "Group times\n  status/basic " in out, out


def _spy_on_reports(monkeypatch: pytest.MonkeyPatch) -> list[Report]:
    """The Reports `mscts run` prints, in order, as it prints them."""
    shown: list[Report] = []

    def spy(report: Report, *, verbose: bool, color: bool) -> str:
        shown.append(report)
        return render_text(report, verbose=verbose, color=color)

    monkeypatch.setattr(cli, "render_text", spy)
    return shown


@pytest.mark.parametrize("verbose", [False, True], ids=["default", "verbose"])
def test_out_writes_the_report_as_json_and_markdown_into_a_new_folder(
    fakes: Fakes,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    verbose: bool,
) -> None:
    fakes(pumpkin_description="not vanilla")
    shown = _spy_on_reports(monkeypatch)
    out_dir = tmp_path / "reports" / "pumpkin"
    options = ["--verbose"] if verbose else []

    code, out, err = _run(
        capsys, "--candidate", "pumpkin", "--repeat", "1", "--out", f"{out_dir}/", *options
    )

    assert code == 0, err
    [report] = shown
    written = f"Report written to {out_dir}/report.json and {out_dir}/report.md\n"
    assert out == render_text(report, verbose=verbose) + written
    assert report_json.loads((out_dir / "report.json").read_text()) == report
    assert (out_dir / "report.md").read_text() == render_markdown(report, verbose=verbose)
    assert sorted(path.name for path in out_dir.iterdir()) == ["report.json", "report.md"]


def test_out_overwrites_an_earlier_report(
    fakes: Fakes, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    fakes()
    (tmp_path / "report.json").write_text("an earlier Run")
    (tmp_path / "report.md").write_text("an earlier Run")

    code, _, err = _run(capsys, "--candidate", "pumpkin", "--repeat", "1", "--out", str(tmp_path))

    assert code == 0, err
    assert report_json.loads((tmp_path / "report.json").read_text()).candidate.name == "pumpkin"
    assert (tmp_path / "report.md").read_text().startswith("# Running tests against pumpkin\n")


def test_an_out_folder_that_cannot_be_made_fails_before_the_run(
    fakes: Fakes, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    fakes()
    (tmp_path / "taken").write_text("a file, not a folder")

    code, out, err = _run(capsys, "--candidate", "pumpkin", "--out", str(tmp_path / "taken"))

    assert (code, out) == (1, "")
    assert err == f"mscts: cannot create the --out folder {tmp_path / 'taken'}: File exists\n"


def test_a_report_file_that_cannot_be_written_fails_after_printing_the_report(
    fakes: Fakes, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    fakes()
    (tmp_path / "report.md").mkdir()

    code, out, err = _run(capsys, "--candidate", "pumpkin", "--repeat", "1", "--out", str(tmp_path))

    assert code == 1
    assert out.startswith("Running tests against pumpkin\n"), out
    assert "Report written" not in out
    assert err.endswith(f"\nmscts: cannot write {tmp_path / 'report.md'}: Is a directory\n"), err


def _refuse(_: Report) -> str:
    msg = "Out of range float values are not JSON compliant: inf"
    raise ValueError(msg)


def _lone_surrogate(_: Report, *, verbose: bool) -> str:
    del verbose
    return "a name with a lone surrogate: " + chr(0xD800)


@dataclasses.dataclass(frozen=True)
class Unwritable:
    """A report file whose text cannot be made or encoded, and the reason mscts gives."""

    module: object
    name: str
    fake: object
    file: str
    reason: str


UNWRITABLE = {
    "json-refuses-a-value": Unwritable(
        report_json, "dumps", _refuse, "report.json", "Out of range float values"
    ),
    "md-cannot-be-encoded": Unwritable(
        cli, "render_markdown", _lone_surrogate, "report.md", "'utf-8' codec can't encode"
    ),
}


@pytest.mark.parametrize("case", UNWRITABLE.values(), ids=UNWRITABLE.keys())
def test_a_report_file_that_cannot_be_encoded_fails_naming_it(
    fakes: Fakes,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: Unwritable,
) -> None:
    fakes()
    monkeypatch.setattr(case.module, case.name, case.fake)

    code, out, err = _run(capsys, "--candidate", "pumpkin", "--repeat", "1", "--out", str(tmp_path))

    assert code == 1
    assert out.startswith("Running tests against pumpkin\n"), out
    assert "Report written" not in out
    said = f"mscts: cannot write {tmp_path / case.file}: {case.reason}"
    assert err.splitlines()[-1].startswith(said), err


def test_a_failed_report_file_leaves_both_earlier_files_as_they_were(
    fakes: Fakes,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fakes()
    folder = tmp_path / "reports"
    folder.mkdir()
    (folder / "report.json").write_text("an earlier Run")
    (folder / "report.md").write_text("an earlier Run")
    monkeypatch.setattr(cli, "render_markdown", _lone_surrogate)

    code, _, _ = _run(capsys, "--candidate", "pumpkin", "--repeat", "1", "--out", str(folder))

    assert code == 1
    assert (folder / "report.json").read_text() == "an earlier Run"
    assert (folder / "report.md").read_text() == "an earlier Run"
    assert sorted(path.name for path in folder.iterdir()) == ["report.json", "report.md"]


def test_a_run_report_carries_no_note_about_unbuilt_output(
    fakes: Fakes, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes()
    shown = _spy_on_reports(monkeypatch)

    code, _, _ = _run(capsys, "--candidate", "pumpkin", "--group", PING_AND_BASIC, "--repeat", "1")

    assert code == 0
    assert [report.notes for report in shown] == [()]


def test_a_run_colours_the_marks_when_asked(
    fakes: Fakes, capsys: pytest.CaptureFixture[str]
) -> None:
    fakes()

    code = cli.main(["run", "--candidate", "pumpkin", "--repeat", "1"], color=True)

    out, _ = capsys.readouterr()
    assert code == 0
    assert "\x1b[32m✓\x1b[0m status/basic/" in out, out


def test_a_piped_run_is_plain(fakes: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    fakes()

    _, out, _ = _run(capsys, "--candidate", "pumpkin", "--repeat", "1")

    assert "\x1b" not in out, out


class _Stream:
    def __init__(self, *, terminal: bool) -> None:
        self.terminal = terminal

    def isatty(self) -> bool:
        return self.terminal


@pytest.mark.parametrize(
    ("terminal", "environ", "expected"),
    [
        (True, {}, True),
        (False, {}, False),
        (True, {"NO_COLOR": "1"}, False),
        (True, {"NO_COLOR": ""}, True),
    ],
    ids=["terminal", "piped", "no-color", "empty-no-color"],
)
def test_colour_is_for_a_terminal_without_no_color(
    *, terminal: bool, environ: dict[str, str], expected: bool
) -> None:
    assert cli._wants_color(_Stream(terminal=terminal), environ) is expected  # noqa: SLF001
