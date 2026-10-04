"""What a failing Self-check says: each Verdict that is not `match`, and what differed (#84).

pytest cuts a Verdict's repr after a few dozen characters, which hides the one thing a Group's
author needs, the field that differs between two vanilla Instances.
"""

from pathlib import Path

from support.selfcheck import (
    MAX_DIVERGENCES,
    MAX_VERDICTS,
    describe_unmatched,
    keep_timeline,
    keep_timelines_and_describe,
)

from mscts.compare import (
    ABSENT,
    OBSERVE_CLOSE,
    OBSERVE_OPEN,
    Divergence,
    DivergenceKind,
    Outcome,
    Verdict,
)
from mscts.run import GroupResult, RunResult, SideSummary
from mscts.timeline import timeline
from mscts.transcript import Transcript
from tests.compare.build import transcript


def divergence(
    kind: DivergenceKind = "field", path: str | None = "players.online", **values: object
) -> Divergence:
    return Divergence(
        bot="status",
        index=0,
        kind=kind,
        packet="minecraft:status_response",
        path=path,
        reference=values.get("reference", 0),
        candidate=values.get("candidate", 1),
        test_case="players.online",
    )


def mismatch(group_id: str, *divergences: Divergence) -> Verdict:
    return Verdict(group_id=group_id, outcome=Outcome.MISMATCH, divergences=divergences)


def test_a_mismatch_names_the_group_and_each_difference_with_both_values() -> None:
    verdict = mismatch(
        "status/basic",
        divergence(),
        divergence("missing", path=None, reference="x", candidate=ABSENT),
    )

    assert describe_unmatched([verdict]) == (
        "status/basic: mismatch\n"
        "  status: field minecraft:status_response players.online: 0 vs 1\n"
        "  status: missing minecraft:status_response: 'x' vs ABSENT"
    )


def test_a_verdict_with_a_detail_and_no_differences_says_it() -> None:
    verdict = Verdict(
        group_id="join/basic", outcome=Outcome.ERROR, detail="the Reference failed: TimeoutError"
    )

    assert describe_unmatched([verdict]) == (
        "join/basic: error: the Reference failed: TimeoutError"
    )


def test_differences_past_the_first_few_are_counted_not_listed() -> None:
    many = [divergence(path=f"field{n}") for n in range(MAX_DIVERGENCES + 2)]

    lines = describe_unmatched([mismatch("status/basic", *many)]).splitlines()

    assert len(lines) == 1 + MAX_DIVERGENCES + 1
    assert lines[-1] == "  ... and 2 more differences"


def played(*kept: tuple[Transcript, Transcript] | None) -> RunResult:
    """A Run of `status/basic`, a repetition per item of `kept`: its Transcripts, if any."""
    verdicts = tuple(
        Verdict(group_id="status/basic", outcome=Outcome.MATCH if k is None else Outcome.ERROR)
        for k in kept
    )
    side = SideSummary(name="vanilla", version="26.3", startup=())
    group = GroupResult(
        group_id="status/basic",
        verdicts=verdicts,
        reference=((),) * len(kept),
        candidate=((),) * len(kept),
        transcripts=kept,
    )
    return RunResult(results=(group,), reference=side, candidate=side)


def test_a_failure_keeps_each_unmatched_plays_timelines_and_names_their_file(
    tmp_path: Path,
) -> None:
    # #162: a flaky play can be diagnosed from where each packet arrived.
    reference = transcript(OBSERVE_OPEN, group_id="status/basic", server="vanilla")
    candidate = transcript(OBSERVE_CLOSE, group_id="status/basic", server="other")

    message = keep_timelines_and_describe(played(None, (reference, candidate)), tmp_path)

    kept = tmp_path / "status-basic.2.txt"
    assert kept.read_text() == f"{timeline(reference)}\n\n{timeline(candidate)}\n"
    assert message.splitlines() == [
        "status/basic: error",
        "The timelines of the plays that did not match:",
        f"  {kept}",
    ]
    assert list(tmp_path.iterdir()) == [kept], "a play that matched keeps nothing"


def test_a_plays_timelines_are_kept_in_one_file_in_a_folder_it_makes(tmp_path: Path) -> None:
    # #238: a test that compares two plays itself, with no Verdict, keeps them too.
    one = transcript(OBSERVE_OPEN, group_id="probe/join-until", server="vanilla")
    other = transcript(OBSERVE_CLOSE, group_id="probe/join-until", server="vanilla")
    path = tmp_path / "timelines" / "probe-join-until.3.txt"

    assert keep_timeline((one, other), path) == path
    assert path.read_text() == f"{timeline(one)}\n\n{timeline(other)}\n"


def test_verdicts_past_the_first_few_are_counted_not_listed() -> None:
    verdicts = [mismatch("status/basic", divergence()) for _ in range(MAX_VERDICTS + 3)]

    lines = describe_unmatched(verdicts).splitlines()

    assert lines[-1] == "... and 3 more Verdicts that are not match"
    assert sum(line.startswith("status/basic: mismatch") for line in lines) == MAX_VERDICTS
