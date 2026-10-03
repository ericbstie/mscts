"""`mscts run` end to end: live vanilla against the installed Pumpkin."""

import pytest

from mscts.cli import main

pytestmark = pytest.mark.candidate


@pytest.mark.parametrize("verbose", [False, True], ids=["default", "verbose"])
def test_mscts_run_against_pumpkin_prints_a_report(
    capsys: pytest.CaptureFixture[str], *, verbose: bool
) -> None:
    options = ["--verbose"] if verbose else []
    code = main(["run", "--candidate", "pumpkin", "--repeat", "1", *options])

    out, err = capsys.readouterr()
    assert code == 0, err
    assert out.startswith("Running tests against pumpkin\n"), out
    assert out.splitlines()[-1].startswith("Took "), out
    # A Comparison that raises is that Group's `error`, and the Run goes on (#174), so only
    # this tier sees a Comparison bug a Candidate's packets set off.
    assert "Error: the Comparison failed" not in out, out

    if verbose:
        assert "  Reference    vanilla 26.3 (sha256 " in out, out
        assert "  Candidate    pumpkin nightly " in out, out
        assert "installed version unknown" not in out, out
        assert "Group times\n  status/basic " in out, out
        assert "  status/ping " in out, out
    else:
        assert "Group times" not in out, out
