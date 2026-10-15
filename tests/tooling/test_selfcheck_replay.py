"""When a statistical Group's Self-check is played once more (#388).

A Self-check compares vanilla with vanilla at the 1% level, so a statistical Group rejects by
chance 1 time in 100. Only that kind of rejection, a `mismatch` made of `distribution`
Divergences, is replayed with fresh plays; anything else fails at once.
"""

from support.selfcheck import may_replay

from mscts.compare import Divergence, DivergenceKind, Outcome, Verdict
from mscts.group import Group, GroupContext, GroupKind


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
