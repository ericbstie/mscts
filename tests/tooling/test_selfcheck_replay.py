"""When a statistical Group's Self-check is played once more (#388).

A Self-check compares vanilla with vanilla at the 1% level, so a statistical Group rejects by
chance 1 time in 100. Only that kind of rejection, a `mismatch` made of `distribution`
Divergences, is replayed with fresh plays; anything else fails at once.
"""

from collections.abc import Iterable
from pathlib import Path

import pytest
from support.selfcheck import describe_failure, may_replay, play_and_replay

from mscts.compare import Divergence, DivergenceKind, Outcome, Verdict
from mscts.group import Group, GroupContext, GroupKind
from mscts.run import GroupResult, RunResult, SideSummary


async def _nothing(_: GroupContext) -> None:
    pass


STATISTICAL = Group(id="spawn/join-position", run=_nothing, kind=GroupKind.STATISTICAL)
EXACT = Group(id="status/basic", run=_nothing)


def divergence(kind: DivergenceKind) -> Divergence:
    return Divergence(
        bot="" if kind in {"distribution", "failed"} else "status",
        index=0,
        kind=kind,
        packet="",
        path=None,
        reference=0,
        candidate=1,
        test_case="spawn.distance",
    )


def verdict(group: Group, outcome: Outcome, *kinds: DivergenceKind) -> Verdict:
    return Verdict(
        group_id=group.id,
        outcome=outcome,
        divergences=tuple(divergence(kind) for kind in kinds),
    )


def test_a_statistical_group_rejected_only_by_its_distributions_is_replayed() -> None:
    rejected = verdict(STATISTICAL, Outcome.MISMATCH, "distribution", "distribution")

    assert may_replay([STATISTICAL], [rejected])


def test_a_match_is_not_replayed() -> None:
    assert not may_replay([STATISTICAL], [verdict(STATISTICAL, Outcome.MATCH)])


def test_an_exact_group_is_never_replayed() -> None:
    assert not may_replay([EXACT], [verdict(EXACT, Outcome.MISMATCH, "distribution")])


def test_an_error_is_not_replayed() -> None:
    assert not may_replay([STATISTICAL], [verdict(STATISTICAL, Outcome.ERROR)])


def test_a_failed_divergence_is_not_replayed() -> None:
    rejected = verdict(STATISTICAL, Outcome.MISMATCH, "distribution", "failed")

    assert not may_replay([STATISTICAL], [rejected])


def test_a_mismatch_with_no_divergence_is_not_replayed() -> None:
    assert not may_replay([STATISTICAL], [verdict(STATISTICAL, Outcome.MISMATCH)])


def test_a_field_divergence_is_not_replayed() -> None:
    assert not may_replay([STATISTICAL], [verdict(STATISTICAL, Outcome.MISMATCH, "field")])


def test_a_chance_rejection_with_a_failing_prerequisite_is_not_replayed() -> None:
    rejected = verdict(STATISTICAL, Outcome.MISMATCH, "distribution")
    broken = verdict(EXACT, Outcome.MISMATCH, "field")

    assert not may_replay([EXACT, STATISTICAL], [broken, rejected])


def test_a_matching_prerequisite_does_not_stop_the_replay() -> None:
    rejected = verdict(STATISTICAL, Outcome.MISMATCH, "distribution")
    matched = verdict(EXACT, Outcome.MATCH)

    assert may_replay([EXACT, STATISTICAL], [matched, rejected])


def run_of(*verdicts: Verdict) -> RunResult:
    """A Run with one repetition: each Verdict is its Group's."""
    side = SideSummary(name="vanilla", version="26.3", startup=())
    results = tuple(
        GroupResult(
            group_id=one.group_id,
            verdicts=(one,),
            reference=((),),
            candidate=((),),
            transcripts=(None,),
        )
        for one in verdicts
    )
    return RunResult(results=results, reference=side, candidate=side)


class FakePlay:
    """Plays a scripted Run per call, and remembers the workdir each was given."""

    def __init__(self, runs: Iterable[RunResult]) -> None:
        self._runs = iter(runs)
        self.workdirs: list[Path] = []

    async def __call__(self, workdir: Path) -> RunResult:
        self.workdirs.append(workdir)
        return next(self._runs)


REJECTED = run_of(verdict(STATISTICAL, Outcome.MISMATCH, "distribution"))
MATCHED = run_of(verdict(STATISTICAL, Outcome.MATCH))


@pytest.mark.asyncio
async def test_a_rejection_then_a_match_passes_after_one_replay(tmp_path: Path) -> None:
    play = FakePlay([REJECTED, MATCHED])

    plays = await play_and_replay([STATISTICAL], play, tmp_path)

    assert plays == (REJECTED, MATCHED)
    assert describe_failure(plays, tmp_path / "timelines") == ""


@pytest.mark.asyncio
async def test_the_replay_is_played_in_a_workdir_of_its_own(tmp_path: Path) -> None:
    play = FakePlay([REJECTED, MATCHED])

    await play_and_replay([STATISTICAL], play, tmp_path)

    assert len(set(play.workdirs)) == 2
    assert all(tmp_path in workdir.parents for workdir in play.workdirs)


@pytest.mark.asyncio
async def test_a_match_is_played_once(tmp_path: Path) -> None:
    play = FakePlay([MATCHED])

    plays = await play_and_replay([STATISTICAL], play, tmp_path)

    assert plays == (MATCHED,)
    assert len(play.workdirs) == 1


@pytest.mark.asyncio
async def test_two_rejections_fail_and_show_both_verdicts(tmp_path: Path) -> None:
    other = run_of(
        Verdict(
            group_id=STATISTICAL.id,
            outcome=Outcome.MISMATCH,
            divergences=(divergence("distribution"), divergence("distribution")),
        )
    )
    play = FakePlay([REJECTED, other])

    plays = await play_and_replay([STATISTICAL], play, tmp_path)

    message = describe_failure(plays, tmp_path / "timelines")
    assert plays == (REJECTED, other)
    assert message.splitlines()[0] == "Played again after the first play was rejected."
    assert message.count("spawn/join-position: mismatch") == 2
    assert "First play:" in message
    assert "Replay:" in message


@pytest.mark.asyncio
async def test_an_error_fails_without_a_replay(tmp_path: Path) -> None:
    errored = run_of(verdict(STATISTICAL, Outcome.ERROR))
    play = FakePlay([errored])

    plays = await play_and_replay([STATISTICAL], play, tmp_path)

    assert len(play.workdirs) == 1
    assert describe_failure(plays, tmp_path / "timelines") == "spawn/join-position: error"


@pytest.mark.asyncio
async def test_a_failed_divergence_fails_without_a_replay(tmp_path: Path) -> None:
    failed = run_of(verdict(STATISTICAL, Outcome.MISMATCH, "distribution", "failed"))
    play = FakePlay([failed])

    plays = await play_and_replay([STATISTICAL], play, tmp_path)

    assert len(play.workdirs) == 1
    assert describe_failure(plays, tmp_path / "timelines") != ""


@pytest.mark.asyncio
async def test_an_exact_group_that_does_not_match_is_never_replayed(tmp_path: Path) -> None:
    mismatched = run_of(verdict(EXACT, Outcome.MISMATCH, "field"))
    play = FakePlay([mismatched])

    await play_and_replay([EXACT], play, tmp_path)

    assert len(play.workdirs) == 1
