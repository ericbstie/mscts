"""An Instance a failed Group left frozen is unusable for the rest of the Run (#228)."""

import functools
from collections.abc import Sequence
from pathlib import Path

import pytest

from mscts import run as run_module
from mscts.compare import Outcome, Verdict
from mscts.group import Group, GroupContext, GroupKind
from mscts.net import Endpoint
from mscts.report import GroupLine, LineResult, Totals, report_lines, totals
from mscts.run import GroupResult, run
from tests.group.test_control import ControlServer
from tests.run.occupancy import attached
from tests.test_report import _report

GROUP_TIMEOUT_S = 0.5
"""Each Bot operation's bound here: short, since the frozen side never answers its unfreeze."""

UNSETTLED = run_module._unsettled  # noqa: SLF001 - the real wait, which `quick` replaces
"""The wait for no player online, for a test that puts it back."""


def refusing_to_unfreeze() -> ControlServer:
    """A fake whose Control answers no command from `tick unfreeze` on."""

    def stop_at_unfreeze(command: str) -> None:
        if command == "tick unfreeze":
            server.answers_markers = False

    server = ControlServer(on_command=stop_at_unfreeze)
    return server


async def _fails_frozen(context: GroupContext) -> None:
    await context.freeze()
    msg = "the Group failed while the world was frozen"
    raise RuntimeError(msg)


async def _joins(context: GroupContext) -> None:
    bot = await context.bot("alice")
    await bot.join()


FAILS_FROZEN = Group(id="test/fails-frozen", run=_fails_frozen, kind=GroupKind.TICK_EXACT)
JOINS = Group(id="test/joins", run=_joins)


@pytest.fixture(autouse=True)
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bound each Bot operation briefly, and skip the wait for no player online."""
    monkeypatch.setattr(
        run_module,
        "run_group",
        functools.partial(run_module.run_group, timeout_s=GROUP_TIMEOUT_S),
    )

    async def settled(*_: object) -> None:
        return None

    monkeypatch.setattr(run_module, "_unsettled", settled)


async def _stays_frozen(context: GroupContext) -> None:
    await context.freeze()


STAYS_FROZEN = Group(id="test/stays-frozen", run=_stays_frozen, kind=GroupKind.TICK_EXACT)


async def _later(group: Group, frozen: str, tmp_path: Path, *, repeat: int = 1) -> list[Verdict]:
    """The Verdicts of JOINS, played after `group` with the `frozen` side refusing to unfreeze."""
    stuck = {side: frozen in {side, "both"} for side in ("Reference", "Candidate")}
    servers = [refusing_to_unfreeze() if stuck[side] else ControlServer() for side in stuck]
    async with (
        attached("vanilla", servers[0]) as reference,
        attached("vanilla", servers[1]) as candidate,
    ):
        verdicts = await run([group, JOINS], reference, candidate, workdir=tmp_path, repeat=repeat)
    return [verdict for verdict in verdicts if verdict.group_id == JOINS.id]


@pytest.mark.asyncio
@pytest.mark.parametrize("group", [FAILS_FROZEN, STAYS_FROZEN], ids=["failed", "ended"])
@pytest.mark.parametrize("frozen", ["Reference", "both"])
async def test_a_group_after_one_that_left_the_reference_frozen_is_an_error(
    group: Group, frozen: str, tmp_path: Path
) -> None:
    later = await _later(group, frozen, tmp_path, repeat=2)

    detail = f"the Reference is unusable: {group.id} left its world frozen"
    if frozen == "both":
        detail += f"; the Candidate is unusable: {group.id} left its world frozen"
    assert [(verdict.outcome, verdict.detail) for verdict in later] == [(Outcome.ERROR, detail)] * 2


@pytest.mark.asyncio
@pytest.mark.parametrize("group", [FAILS_FROZEN, STAYS_FROZEN], ids=["failed", "ended"])
async def test_a_group_after_one_that_left_the_candidate_frozen_fails_and_is_scored(
    group: Group, tmp_path: Path
) -> None:
    # #228 review: an `error` is left out of the Score, so a Candidate that broke its
    # world would score better than one that did not.
    later = await _later(group, "Candidate", tmp_path, repeat=2)

    what = f"{group.id} left its world frozen"
    assert [(verdict.outcome, verdict.detail) for verdict in later] == [
        (Outcome.MISMATCH, f"the Candidate failed: {what}")
    ] * 2
    assert all(
        [(d.kind, d.candidate, d.test_case) for d in verdict.divergences] == [("failed", what, "")]
        for verdict in later
    ), later


@pytest.mark.asyncio
async def test_a_candidate_left_frozen_fails_each_test_case_of_the_references_play(
    tmp_path: Path,
) -> None:
    # #266, audit M2: the Reference is still played, so a Candidate that broke its world
    # fails every test case sending every value wrong would, and the Group's own line.
    [verdict] = await _later(STAYS_FROZEN, "Candidate", tmp_path)
    played = await _reference_test_cases(tmp_path / "reference")

    assert verdict.test_cases == played
    lines = report_lines(_report(GroupResult(JOINS.id, (verdict,), (), ())))
    what = f"{STAYS_FROZEN.id} left its world frozen"
    assert lines[-1] == GroupLine(JOINS.id, LineResult.FAIL, f"Candidate failed: {what}")
    assert totals(lines) == Totals(passed=0, failed=len(played) + 1, not_tested=0, errors=0)


@pytest.mark.asyncio
async def test_only_the_reference_is_waited_on_while_the_candidate_is_frozen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A frozen world never ticks, so it never drops a closed Bot's player: waiting on it
    # would cost the whole deadline before each later Group.
    waited: list[int] = []

    async def settled(group: Group, endpoints: Sequence[Endpoint]) -> None:
        del group
        waited.append(len(endpoints))

    monkeypatch.setattr(run_module, "_unsettled", settled)
    await _later(STAYS_FROZEN, "Candidate", tmp_path)

    assert waited == [2, 1], "both sides before the freeze, then the Reference alone"


@pytest.mark.asyncio
async def test_no_side_is_waited_on_once_the_reference_is_frozen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    waited: list[int] = []

    async def settled(group: Group, endpoints: Sequence[Endpoint]) -> None:
        del group
        waited.append(len(endpoints))

    monkeypatch.setattr(run_module, "_unsettled", settled)
    await _later(STAYS_FROZEN, "Reference", tmp_path)

    assert waited == [2]


@pytest.mark.asyncio
async def test_a_reference_unsettled_while_the_candidate_is_frozen_is_an_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(run_module, "_unsettled", UNSETTLED)
    polls: list[Endpoint] = []

    async def poll(endpoint: Endpoint, *, deadline_s: float) -> None:
        del deadline_s
        polls.append(endpoint)
        if len(polls) > 2:  # the later Group's, on the Reference alone
            msg = "vanilla stopped"
            raise RuntimeError(msg)

    monkeypatch.setattr(run_module, "until_no_player_online", poll)
    [verdict] = await _later(STAYS_FROZEN, "Candidate", tmp_path)

    detail = (
        "the Reference failed: the wait for no player online failed: RuntimeError: vanilla stopped"
    )
    assert verdict == Verdict(JOINS.id, Outcome.ERROR, detail=detail)


async def _reference_test_cases(tmp_path: Path) -> tuple[str, ...]:
    """The test cases of JOINS, played on two fakes that both unfreeze."""
    async with (
        attached("vanilla", ControlServer()) as reference,
        attached("vanilla", ControlServer()) as candidate,
    ):
        [verdict] = await run([JOINS], reference, candidate, workdir=tmp_path)
    assert verdict.outcome is Outcome.MATCH, verdict
    assert verdict.test_cases, "JOINS must have test cases for this to show anything"
    return verdict.test_cases


@pytest.mark.asyncio
async def test_a_side_that_unfroze_stays_usable(tmp_path: Path) -> None:
    async with (
        attached("vanilla", ControlServer()) as reference,
        attached("vanilla", ControlServer()) as candidate,
    ):
        verdicts = await run([FAILS_FROZEN, JOINS], reference, candidate, workdir=tmp_path)

    assert [verdict.outcome for verdict in verdicts] == [Outcome.ERROR, Outcome.MATCH], verdicts
