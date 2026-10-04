"""`mscts run` end to end: live vanilla against the installed Pumpkin."""

import re
from pathlib import Path

import pytest

from mscts import report_json
from mscts.cli import main

pytestmark = pytest.mark.candidate


@pytest.mark.parametrize("verbose", [False, True], ids=["default", "verbose"])
def test_mscts_run_against_pumpkin_prints_a_report(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, *, verbose: bool
) -> None:
    options = ["--verbose"] if verbose else []
    code = main(
        ["run", "--candidate", "pumpkin", "--repeat", "1", "--out", str(tmp_path), *options]
    )

    out, err = capsys.readouterr()
    assert code == 0, err
    # The installed build follows the name on the first line; its version differs between machines.
    assert out.startswith("Running tests against pumpkin "), out
    lines = out.splitlines()
    assert re.fullmatch(r"\d+ passed, \d+ failed\. \(\d+(\.\d+)?%\)", lines[-3]), out
    assert lines[-2].startswith("Took "), out
    assert lines[-1] == f"Report written to {tmp_path / 'report.json'} and {tmp_path / 'report.md'}"
    # Every value a real Candidate's Comparison holds is one report.json can write and read.
    report = report_json.loads((tmp_path / "report.json").read_text())
    assert report.candidate.name == "pumpkin"
    markdown = (tmp_path / "report.md").read_text()
    assert markdown.startswith("# Running tests against pumpkin "), markdown
    # A Comparison that raises on what a Candidate sent is that Candidate's `mismatch` (#239),
    # and the Run goes on (#174), so only this tier sees a Comparison bug a Candidate's
    # packets set off: as an `Error` line or a `Candidate failed` one.
    assert "the Comparison failed" not in out, out

    if verbose:
        assert "  Reference    vanilla 26.3 (sha256 " in out, out
        assert "installed version unknown" not in out, out
        assert "Group times\n  status/basic " in out, out
        assert "  status/ping " in out, out
    else:
        assert not lines[1].startswith("  Reference"), out
        assert "Group times" not in out, out
