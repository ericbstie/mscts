"""What a failing Self-check says: each Verdict that is not `match`, and what differed (#84).

pytest cuts a Verdict's repr after a few dozen characters, which hides the one thing a Group's
author needs, the field that differs between two vanilla Instances.
"""

from support.selfcheck import MAX_DIVERGENCES, MAX_VERDICTS, describe_unmatched

from mscts.compare import ABSENT, Divergence, DivergenceKind, Outcome, Verdict


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


def test_verdicts_past_the_first_few_are_counted_not_listed() -> None:
    verdicts = [mismatch("status/basic", divergence()) for _ in range(MAX_VERDICTS + 3)]

    lines = describe_unmatched(verdicts).splitlines()

    assert lines[-1] == "... and 3 more Verdicts that are not match"
    assert sum(line.startswith("status/basic: mismatch") for line in lines) == MAX_VERDICTS
