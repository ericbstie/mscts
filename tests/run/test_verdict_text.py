"""A Self-check's failure message names each Divergence of the plays that did not match (#456)."""

from support.verdict_text import describe_mismatches

from mscts.compare import ABSENT, TICK_PATH, Divergence, Outcome, Verdict

_GROUP = "probe/repeater-stepped"


def _divergence(index: int, path: str | None = "known_packs[0].version") -> Divergence:
    return Divergence(
        bot="alice",
        index=index,
        kind="field",
        packet="select_known_packs",
        path=path,
        reference="1.21",
        candidate="1.22",
        test_case="select_known_packs.known_packs[].version",
    )


def _match() -> Verdict:
    return Verdict(group_id=_GROUP, outcome=Outcome.MATCH)


def test_each_divergence_gets_a_line_with_its_group_play_packet_path_values_and_index() -> None:
    mismatch = Verdict(
        group_id=_GROUP,
        outcome=Outcome.MISMATCH,
        divergences=(_divergence(4), _divergence(9, path=TICK_PATH)),
    )

    text = describe_mismatches([_match(), mismatch, _match()])

    expected = (
        "probe/repeater-stepped play 2 of 3: bot 'alice' select_known_packs at 4,"
        " known_packs[0].version: reference '1.21', candidate '1.22'\n"
        "probe/repeater-stepped play 2 of 3: bot 'alice' select_known_packs at 9,"
        " (tick): reference '1.21', candidate '1.22'"
    )
    assert text == expected, text


def test_a_whole_packet_divergence_names_no_path_and_shows_absent() -> None:
    missing = Divergence(
        bot="alice",
        index=7,
        kind="missing",
        packet="block_update",
        path=None,
        reference={"state": 3},
        candidate=ABSENT,
        test_case="block_update",
    )
    mismatch = Verdict(group_id=_GROUP, outcome=Outcome.MISMATCH, divergences=(missing,))

    text = describe_mismatches([mismatch])

    expected = (
        "probe/repeater-stepped play 1 of 1: bot 'alice' block_update at 7, missing:"
        " reference {'state': 3}, candidate ABSENT"
    )
    assert text == expected, text


def test_the_omitted_divergences_are_counted() -> None:
    mismatch = Verdict(
        group_id=_GROUP, outcome=Outcome.MISMATCH, divergences=(_divergence(4),), omitted=12
    )

    text = describe_mismatches([mismatch])

    assert (
        text.splitlines()[-1] == "probe/repeater-stepped play 1 of 1: 12 more Divergences omitted"
    )


def test_a_verdict_without_divergences_gives_its_outcome_and_detail() -> None:
    error = Verdict(group_id=_GROUP, outcome=Outcome.ERROR, detail="no answer within 10 s")

    text = describe_mismatches([_match(), error])

    assert text == "probe/repeater-stepped play 2 of 2: error: no answer within 10 s", text


def test_a_play_counts_among_its_own_groups_verdicts() -> None:
    other = "probe/other"
    verdicts = [
        _match(),
        Verdict(group_id=other, outcome=Outcome.ERROR, detail="x"),
        Verdict(group_id=_GROUP, outcome=Outcome.ERROR, detail="y"),
        Verdict(group_id=other, outcome=Outcome.MATCH),
    ]

    text = describe_mismatches(verdicts)

    expected = "probe/other play 1 of 2: error: x\nprobe/repeater-stepped play 2 of 2: error: y"
    assert text == expected, text


def test_matching_plays_give_no_text() -> None:
    assert describe_mismatches([_match(), _match()]) == ""
