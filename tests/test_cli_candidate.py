"""`mscts run` end to end: live vanilla against the installed Pumpkin."""

import pytest

from mscts.cli import main

pytestmark = pytest.mark.candidate


def test_mscts_run_against_pumpkin_prints_a_report(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["run", "--candidate", "pumpkin", "--repeat", "1"])

    out, err = capsys.readouterr()
    assert code == 0, err
    assert out.startswith("Running tests against pumpkin\n"), out
    assert out.splitlines()[-1].startswith("Took "), out
