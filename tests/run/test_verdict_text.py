"""A failure message names each Divergence of the plays that did not match (#456, #471)."""

from collections.abc import Sequence
from pathlib import Path

from support.verdict_text import describe_mismatches, keep_timeline

from mscts.compare import (
    ABSENT,
    OBSERVE_CLOSE,
    OBSERVE_OPEN,
    TICK_PATH,
    Divergence,
    Outcome,
    Verdict,
)
from mscts.run import GroupResult, RunResult, SideSummary
from mscts.timeline import timeline
from mscts.transcript import Transcript
from tests.compare.build import transcript

_GROUP = "probe/repeater-stepped"
type _Kept = tuple[Transcript, Transcript]


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


def _run_of(verdicts: Sequence[Verdict], kept: dict[int, _Kept] | None = None) -> RunResult:
    """A Run of `verdicts`, one repetition each in order, a Group's after its Group's.

    `kept` holds a Group's Transcripts by the position in `verdicts` of the play they are of.
    """
    kept = kept or {}
    by_group: dict[str, list[int]] = {}
    for position, verdict in enumerate(verdicts):
        by_group.setdefault(verdict.group_id, []).append(position)
    side = SideSummary(name="vanilla", version="26.3", startup=())
    results = tuple(
        GroupResult(
            group_id=group_id,
            verdicts=tuple(verdicts[position] for position in positions),
            reference=((),) * len(positions),
            candidate=((),) * len(positions),
            transcripts=tuple(kept.get(position) for position in positions),
        )
        for group_id, positions in by_group.items()
    )
    return RunResult(results=results, reference=side, candidate=side)


def test_each_divergence_gets_a_line_with_its_group_play_packet_path_values_and_index(
    tmp_path: Path,
) -> None:
    mismatch = Verdict(
        group_id=_GROUP,
        outcome=Outcome.MISMATCH,
        divergences=(_divergence(4), _divergence(9, path=TICK_PATH)),
    )

    text = describe_mismatches(_run_of([_match(), mismatch, _match()]), tmp_path)

    expected = (
        "probe/repeater-stepped play 2 of 3: bot 'alice' select_known_packs at 4,"
        " known_packs[0].version: reference '1.21', candidate '1.22'\n"
        "probe/repeater-stepped play 2 of 3: bot 'alice' select_known_packs at 9,"
        " (tick): reference '1.21', candidate '1.22'"
    )
    assert text == expected, text


def test_a_whole_packet_divergence_names_no_path_and_shows_absent(tmp_path: Path) -> None:
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

    text = describe_mismatches(_run_of([mismatch]), tmp_path)

    expected = (
        "probe/repeater-stepped play 1 of 1: bot 'alice' block_update at 7, missing:"
        " reference {'state': 3}, candidate ABSENT"
    )
    assert text == expected, text


def test_every_divergence_and_every_verdict_is_listed_however_many(tmp_path: Path) -> None:
    # #471: the older text cut a failure at 3 Verdicts and 5 Divergences each.
    divergences = tuple(_divergence(index) for index in range(8))
    mismatch = Verdict(group_id=_GROUP, outcome=Outcome.MISMATCH, divergences=divergences)

    text = describe_mismatches(_run_of([mismatch] * 5), tmp_path)

    assert text.count("probe/repeater-stepped play") == 5 * 8, text
    assert "play 5 of 5: bot 'alice' select_known_packs at 7," in text, text


def test_the_omitted_divergences_are_counted(tmp_path: Path) -> None:
    mismatch = Verdict(
        group_id=_GROUP, outcome=Outcome.MISMATCH, divergences=(_divergence(4),), omitted=12
    )

    text = describe_mismatches(_run_of([mismatch]), tmp_path)

    assert (
        text.splitlines()[-1] == "probe/repeater-stepped play 1 of 1: 12 more Divergences omitted"
    )


def test_a_verdict_without_divergences_gives_its_outcome_and_detail(tmp_path: Path) -> None:
    error = Verdict(group_id=_GROUP, outcome=Outcome.ERROR, detail="no answer within 10 s")

    text = describe_mismatches(_run_of([_match(), error]), tmp_path)

    assert text == "probe/repeater-stepped play 2 of 2: error: no answer within 10 s", text


def test_a_verdict_without_divergences_or_detail_gives_its_outcome(tmp_path: Path) -> None:
    error = Verdict(group_id=_GROUP, outcome=Outcome.ERROR)

    text = describe_mismatches(_run_of([error]), tmp_path)

    assert text == "probe/repeater-stepped play 1 of 1: error", text


def test_a_play_counts_among_its_own_groups_verdicts(tmp_path: Path) -> None:
    other = "probe/other"
    verdicts = [
        _match(),
        Verdict(group_id=other, outcome=Outcome.ERROR, detail="x"),
        Verdict(group_id=_GROUP, outcome=Outcome.ERROR, detail="y"),
        Verdict(group_id=other, outcome=Outcome.MATCH),
    ]

    text = describe_mismatches(_run_of(verdicts), tmp_path)

    expected = "probe/other play 1 of 2: error: x\nprobe/repeater-stepped play 2 of 2: error: y"
    assert text == expected, text


def test_matching_plays_give_no_text_and_keep_nothing(tmp_path: Path) -> None:
    where = tmp_path / "timelines"

    assert describe_mismatches(_run_of([_match(), _match()]), where) == ""
    assert not where.exists()


def test_a_failure_keeps_each_unmatched_plays_timelines_and_names_their_file(
    tmp_path: Path,
) -> None:
    # #162: a flaky play can be diagnosed from where each packet arrived.
    reference = transcript(OBSERVE_OPEN, group_id=_GROUP, server="vanilla")
    candidate = transcript(OBSERVE_CLOSE, group_id=_GROUP, server="other")
    error = Verdict(group_id=_GROUP, outcome=Outcome.ERROR)

    text = describe_mismatches(
        _run_of([_match(), error], kept={1: (reference, candidate)}), tmp_path
    )

    kept = tmp_path / "probe-repeater-stepped.2.txt"
    assert kept.read_text() == f"{timeline(reference)}\n\n{timeline(candidate)}\n"
    assert text.splitlines() == [
        "probe/repeater-stepped play 2 of 2: error",
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
