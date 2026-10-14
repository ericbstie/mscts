"""A statistical Group's Run: `runs` plays per side, judged as distributions (#24).

The fake Group draws its samples from a seeded generator, shifted on the side whose port
the test names, so each test's draws, and so its Verdict, are always the same.
"""

import random
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from support.selfcheck import repetitions, selfcheck_params

from mscts import group as group_module
from mscts import run as run_module
from mscts.compare import ABSENT, Divergence, Outcome, Verdict
from mscts.group import DEFAULT_RUNS, Group, GroupContext, GroupKind, Script
from mscts.net import Endpoint
from mscts.run import Attached, Server, run, selfcheck
from mscts.settle import PlayersStillOnline
from tests.run.fakes import FakeAdapter, attached

_RUNS = 50


def _drawing(shifted_port: int, *, seed: int = 1, plays: Counter[int] | None = None) -> Script:
    """A script sampling `x` from N(0, 1), or N(1, 1) on the Instance at `shifted_port`."""
    rng = random.Random(seed)

    async def draw(context: GroupContext) -> None:
        port = context.endpoint.port
        if plays is not None:
            plays[port] += 1
        context.sample("x", rng.gauss(1.0 if port == shifted_port else 0.0, 1.0))

    return draw


def _statistical(script: Script, *, runs: int = _RUNS) -> Group:
    return Group(id="test/statistical", run=script, kind=GroupKind.STATISTICAL, runs=runs)


type _Scripted = Callable[[Attached, Attached], Group]
"""Builds the Group a test plays, once the two Attached sides' Endpoints are known."""


async def _judged(make: _Scripted, run_token: str, tmp_path: Path) -> Verdict:
    """The Verdict of the Group `make` builds, played once on two fake Attached Instances."""
    async with (
        attached(FakeAdapter("vanilla", run_token), tmp_path / "reference") as reference,
        attached(FakeAdapter("pumpkin", run_token), tmp_path / "candidate") as candidate,
    ):
        [verdict] = await run([make(reference, candidate)], reference, candidate, workdir=tmp_path)
    return verdict


def test_a_group_runs_fifty_times_per_side_by_default() -> None:
    assert DEFAULT_RUNS == 50
    assert _statistical(_drawing(0)).runs == 50
    assert Group(id="test/plain", run=_drawing(0)).runs == DEFAULT_RUNS


def test_a_group_runs_at_least_once() -> None:
    with pytest.raises(ValueError, match="test/statistical runs at least once, not 0"):
        _statistical(_drawing(0), runs=0)


@pytest.mark.asyncio
async def test_samples_from_one_distribution_match(run_token: str, tmp_path: Path) -> None:
    def make(reference: Attached, candidate: Attached) -> Group:
        del reference, candidate
        return _statistical(_drawing(shifted_port=0))

    verdict = await _judged(make, run_token, tmp_path)

    assert (verdict.outcome, verdict.divergences, verdict.test_cases) == (
        Outcome.MATCH,
        (),
        ("x",),
    )


@pytest.mark.asyncio
async def test_shifted_samples_mismatch_with_the_effect_size(
    run_token: str, tmp_path: Path
) -> None:
    def make(reference: Attached, candidate: Attached) -> Group:
        del reference
        return _statistical(_drawing(shifted_port=candidate.endpoint.port))

    verdict = await _judged(make, run_token, tmp_path)

    assert verdict.outcome is Outcome.MISMATCH
    assert verdict.test_cases == ("x",)
    assert verdict.divergences == (
        Divergence(
            bot="",
            index=0,
            kind="distribution",
            packet="",
            path="Kolmogorov-Smirnov D = 0.40, p = 0.00058",
            reference={
                "samples": 50,
                "median": pytest.approx(0.1660829264260152),
                "quartiles": pytest.approx([-0.39263126161364337, 0.6631373849211302]),
            },
            candidate={
                "samples": 50,
                "median": pytest.approx(0.8637264218594136),
                "quartiles": pytest.approx([0.021744350624680386, 1.4127839367477568]),
            },
            test_case="x",
        ),
    )


@pytest.mark.asyncio
async def test_each_side_plays_the_group_runs_times(run_token: str, tmp_path: Path) -> None:
    plays: Counter[int] = Counter()

    def make(reference: Attached, candidate: Attached) -> Group:
        del reference, candidate
        return _statistical(_drawing(0, plays=plays), runs=7)

    await _judged(make, run_token, tmp_path)

    assert sorted(plays.values()) == [7, 7]


def _failing_on(port: int, *, after: int) -> Script:
    """A script that samples `x`, and raises on the Instance at `port` once `after` played."""
    rng = random.Random(3)
    played: Counter[int] = Counter()

    async def draw(context: GroupContext) -> None:
        played[context.endpoint.port] += 1
        if context.endpoint.port == port and played[port] > after:
            msg = "no spawn point"
            raise LookupError(msg)
        context.sample("x", rng.random())

    return draw


@pytest.mark.asyncio
async def test_a_play_that_raises_on_the_reference_is_an_error_and_the_candidate_is_not_played(
    run_token: str, tmp_path: Path
) -> None:
    plays: Counter[int] = Counter()

    def make(reference: Attached, candidate: Attached) -> Group:
        del candidate
        failing = _failing_on(reference.endpoint.port, after=3)

        async def script(context: GroupContext) -> None:
            plays[context.endpoint.port] += 1
            await failing(context)

        return _statistical(script)

    verdict = await _judged(make, run_token, tmp_path)

    assert verdict == Verdict(
        "test/statistical",
        Outcome.ERROR,
        detail="the Reference failed: LookupError: no spawn point",
    )
    assert sorted(plays.values()) == [4]


@pytest.mark.asyncio
async def test_a_play_that_raises_on_the_candidate_fails_each_sample_name(
    run_token: str, tmp_path: Path
) -> None:
    def make(reference: Attached, candidate: Attached) -> Group:
        del reference
        return _statistical(_failing_on(candidate.endpoint.port, after=3))

    verdict = await _judged(make, run_token, tmp_path)

    assert verdict == Verdict(
        "test/statistical",
        Outcome.MISMATCH,
        divergences=(
            Divergence(
                bot="",
                index=0,
                kind="failed",
                packet="",
                path=None,
                reference=ABSENT,
                candidate="LookupError: no spawn point",
                test_case="",
            ),
        ),
        detail="the Candidate failed: LookupError: no spawn point",
        test_cases=("x",),
    )


@pytest.mark.asyncio
async def test_a_name_the_candidate_never_sampled_mismatches_untested(
    run_token: str, tmp_path: Path
) -> None:
    def make(reference: Attached, candidate: Attached) -> Group:
        del candidate
        port = reference.endpoint.port

        async def script(context: GroupContext) -> None:
            context.sample("x", 1.0)
            if context.endpoint.port == port:
                context.sample("mob", "minecraft:zombie")

        return _statistical(script, runs=10)

    verdict = await _judged(make, run_token, tmp_path)

    assert verdict.outcome is Outcome.MISMATCH
    assert verdict.test_cases == ("mob", "x")
    assert verdict.divergences == (
        Divergence(
            bot="",
            index=0,
            kind="distribution",
            packet="",
            path=None,
            reference={"samples": 10, "shares": {"minecraft:zombie": 1.0}},
            candidate={"samples": 0},
            test_case="mob",
        ),
    )


@pytest.mark.asyncio
async def test_categories_are_judged_by_chi_square(run_token: str, tmp_path: Path) -> None:
    def make(reference: Attached, candidate: Attached) -> Group:
        del reference
        port = candidate.endpoint.port

        async def script(context: GroupContext) -> None:
            mob = "minecraft:skeleton" if context.endpoint.port == port else "minecraft:zombie"
            context.sample("mob", mob)

        return _statistical(script)

    verdict = await _judged(make, run_token, tmp_path)

    (divergence,) = verdict.divergences
    assert divergence.path is not None
    assert divergence.path.startswith("chi-square V = 1.00, p = ")
    assert divergence.candidate == {"samples": 50, "shares": {"minecraft:skeleton": 1.0}}


@pytest.mark.asyncio
async def test_a_group_that_samples_nothing_on_the_reference_is_an_error(
    run_token: str, tmp_path: Path
) -> None:
    async def nothing(context: GroupContext) -> None:
        del context

    def make(reference: Attached, candidate: Attached) -> Group:
        del reference, candidate
        return _statistical(nothing, runs=2)

    verdict = await _judged(make, run_token, tmp_path)

    assert verdict == Verdict(
        "test/statistical",
        Outcome.ERROR,
        detail="the Reference recorded no samples: a statistical Group records them with "
        "context.sample",
    )


@dataclass
class _StuckAfter:
    """A wait for no player online that finds one still online at `port` after `after` waits."""

    after: int
    port: int = 0
    waits: Counter[int] = field(default_factory=Counter)

    async def __call__(self, endpoint: Endpoint, *, deadline_s: float) -> None:
        self.waits[endpoint.port] += 1
        if endpoint.port == self.port and self.waits[endpoint.port] > self.after:
            raise PlayersStillOnline(1, ["steve"], deadline_s)


async def _judged_stuck(
    stuck: _StuckAfter, side: int, script: Script, run_token: str, tmp_path: Path
) -> Verdict:
    """The Verdict of `script` when side `side` (0 the Reference) is `stuck`.

    The Run waits once before the Group, then before each play but the first.
    """

    def make(reference: Attached, candidate: Attached) -> Group:
        stuck.port = (reference, candidate)[side].endpoint.port
        return _statistical(script)

    return await _judged(make, run_token, tmp_path)


_STILL_ONLINE = "1 player still online after waiting 2 s: 'steve'"


@pytest.mark.asyncio
async def test_a_reference_with_a_player_still_online_between_runs_is_an_error(
    run_token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stuck = _StuckAfter(after=3)
    monkeypatch.setattr(run_module, "until_no_player_online", stuck)

    verdict = await _judged_stuck(stuck, 0, _drawing(0), run_token, tmp_path)

    assert verdict == Verdict(
        "test/statistical", Outcome.ERROR, detail=f"the Reference failed: {_STILL_ONLINE}"
    )


@pytest.mark.asyncio
async def test_a_candidate_with_a_player_still_online_between_runs_fails_the_group(
    run_token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stuck = _StuckAfter(after=3)
    monkeypatch.setattr(run_module, "until_no_player_online", stuck)
    plays: Counter[int] = Counter()

    verdict = await _judged_stuck(stuck, 1, _drawing(0, plays=plays), run_token, tmp_path)

    assert verdict.outcome is Outcome.MISMATCH
    assert verdict.detail == f"the Candidate failed: {_STILL_ONLINE}"
    assert [(d.kind, d.candidate) for d in verdict.divergences] == [("failed", _STILL_ONLINE)]
    assert verdict.test_cases == ("x",)
    assert plays[stuck.port] == 3  # the fourth wait found the player


@pytest.mark.asyncio
async def test_a_candidate_not_compared_lists_the_sample_names_of_one_reference_play(
    run_token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stuck = _StuckAfter(after=0)  # still online before the Group: the Candidate is not played
    monkeypatch.setattr(run_module, "until_no_player_online", stuck)
    plays: Counter[int] = Counter()

    verdict = await _judged_stuck(stuck, 1, _drawing(0, plays=plays), run_token, tmp_path)

    assert (verdict.outcome, verdict.test_cases) == (Outcome.MISMATCH, ("x",))
    assert verdict.detail == f"the Candidate failed: {_STILL_ONLINE}"
    assert list(plays.values()) == [1]
    assert stuck.port not in plays


@pytest.mark.asyncio
async def test_a_reference_played_alone_that_samples_nothing_is_an_error(
    run_token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stuck = _StuckAfter(after=0)
    monkeypatch.setattr(run_module, "until_no_player_online", stuck)

    async def nothing(context: GroupContext) -> None:
        del context

    verdict = await _judged_stuck(stuck, 1, nothing, run_token, tmp_path)

    assert verdict.outcome is Outcome.ERROR
    assert verdict.detail.startswith("the Reference recorded no samples")


@pytest.mark.asyncio
async def test_a_statistical_selfcheck_compares_two_references_and_does_not_reject(
    fake_server: Callable[..., Server], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    group = _statistical(_drawing(shifted_port=0))
    monkeypatch.setitem(group_module._REGISTERED, group.id, group)  # noqa: SLF001

    verdicts = await selfcheck(
        [group.id], reference=fake_server("vanilla"), workdir=tmp_path, repeat=1
    )

    assert [(verdict.outcome, verdict.test_cases) for verdict in verdicts] == [
        (Outcome.MATCH, ("x",))
    ]


def test_the_selfcheck_tier_leaves_a_statistical_group_to_the_statistical_tier() -> None:
    groups = {
        "test/exact": Group(id="test/exact", run=_drawing(0)),
        "test/statistical": _statistical(_drawing(0)),
    }

    params = selfcheck_params(groups)

    assert [(param.values, [mark.name for mark in param.marks]) for param in params] == [
        (("test/exact",), []),
        (("test/statistical",), ["statistical"]),
    ]


def test_a_statistical_selfcheck_is_one_comparison_whatever_the_repeat() -> None:
    exact = Group(id="test/exact", run=_drawing(0))

    assert repetitions([exact], 20) == 20
    assert repetitions([exact, _statistical(_drawing(0))], 20) == 1
