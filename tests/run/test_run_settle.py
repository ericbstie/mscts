"""A Run plays a Group only once the previous Group's Bots have left the server (#97).

`Bot.close()` only closes the socket, and a server removes the player later (vanilla on its
next tick). So before a Group plays on an Instance, the Run waits until the Instance's status
says no player is online (`mscts.settle`, tested in `test_settle.py`). The fakes here answer
each status request from a script of counts.
"""

from pathlib import Path
from time import perf_counter

import pytest

import mscts.run as run_module
import mscts.settle as settle_module
from mscts.compare import ABSENT, Divergence, Outcome, Verdict
from mscts.group import Group, GroupContext
from mscts.groups import status
from mscts.run import run, run_results
from tests.run.occupancy import Occupancy, attached, named, never_answer

DEADLINE_S = 0.3
"""The deadline the tests that wait for it give a Run: short, so they stay fast."""


@pytest.mark.asyncio
async def test_a_group_plays_after_the_poll_that_finds_no_players_online(tmp_path: Path) -> None:
    reference, candidate = Occupancy(online=(1, 1, 0)), Occupancy(online=(0,))
    polls_at_start: dict[int, int] = {}
    async with (
        attached("one", reference.handler()) as one,
        attached("two", candidate.handler()) as two,
    ):
        by_port = {one.endpoint.port: reference, two.endpoint.port: candidate}

        async def script(context: GroupContext) -> None:
            polls_at_start[context.endpoint.port] = by_port[context.endpoint.port].polls
            await status.basic(context)

        [verdict] = await run(
            [Group(id="test/settle", run=script)], one, two, workdir=tmp_path / "run"
        )

    assert verdict.outcome is Outcome.MATCH
    assert polls_at_start == {one.endpoint.port: 3, two.endpoint.port: 1}


@pytest.mark.asyncio
async def test_the_wait_is_no_part_of_the_time_a_group_took(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    interval_s = 0.2
    monkeypatch.setattr(settle_module, "SETTLE_INTERVAL_S", interval_s)

    async with (
        attached("one", Occupancy(online=(1, 1, 0)).handler()) as one,
        attached("two", Occupancy(online=(0,)).handler()) as two,
    ):
        begun = perf_counter()
        result = await run_results(
            [Group(id="status/basic", run=status.basic)], one, two, workdir=tmp_path / "run"
        )
        waited_s = perf_counter() - begun

    assert waited_s >= 2 * interval_s * 0.9  # the wait was made: two waits between three polls
    [elapsed_s] = result.results[0].elapsed_s
    assert elapsed_s < 2 * interval_s * 0.9, "the Group's time includes the wait"


SAID = "2 players still online after waiting 0.3 s: watcher, control"
"""What a status that never empties, at `DEADLINE_S`, comes to as a sentence."""


async def _play_with_stuck(
    stuck: tuple[str, ...], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Verdict, list[int]]:
    """Run a Group on two fake servers, those in `stuck` never emptying.

    Returns the Group's Verdict, and the ports it played on.
    """
    monkeypatch.setattr(run_module, "SETTLE_TIMEOUT_S", DEADLINE_S)
    sides = {
        role: Occupancy(online=(2,), sample=named("watcher", "control"))
        if role in stuck
        else Occupancy(online=(0,))
        for role in ("Reference", "Candidate")
    }
    played: list[int] = []

    async def script(context: GroupContext) -> None:
        played.append(context.endpoint.port)

    async with (
        attached("one", sides["Reference"].handler()) as one,
        attached("two", sides["Candidate"].handler()) as two,
    ):
        [verdict] = await run(
            [Group(id="test/settle", run=script)], one, two, workdir=tmp_path / "run"
        )
    return verdict, played


@pytest.mark.asyncio
@pytest.mark.timeout(10)  # the deadline is what ends the wait: a hang is the failure
@pytest.mark.parametrize("stuck", [("Reference",), ("Reference", "Candidate")], ids="/".join)
async def test_a_reference_that_never_empties_gives_an_error_naming_the_deadline(
    stuck: tuple[str, ...], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    verdict, played = await _play_with_stuck(stuck, monkeypatch, tmp_path)

    assert verdict.outcome is Outcome.ERROR
    assert verdict.detail == "; ".join(f"the {role} had {SAID}" for role in stuck)
    assert verdict.divergences == ()
    assert played == []


@pytest.mark.asyncio
@pytest.mark.timeout(10)  # the deadline is what ends the wait: a hang is the failure
async def test_a_candidate_that_never_empties_gives_a_mismatch_with_a_failed_divergence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    verdict, played = await _play_with_stuck(("Candidate",), monkeypatch, tmp_path)

    assert verdict.outcome is Outcome.MISMATCH, "a Candidate failure is never an error (audit H3)"
    assert verdict.detail == f"the Candidate failed: {SAID}"
    assert verdict.divergences == (
        Divergence(
            bot="",
            index=0,
            kind="failed",
            packet="",
            path=None,
            reference=ABSENT,
            candidate=SAID,
            test_case="",
        ),
    )
    assert played == []


@pytest.mark.asyncio
@pytest.mark.timeout(5)  # a poll is bounded by a Bot's 10 s: only the deadline can cut it short
async def test_a_status_that_never_answers_does_not_stop_the_group_playing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(run_module, "SETTLE_TIMEOUT_S", DEADLINE_S)
    played: list[int] = []

    async def script(context: GroupContext) -> None:
        played.append(context.endpoint.port)

    async with (
        attached("one", never_answer) as one,
        attached("two", Occupancy(online=(0,)).handler()) as two,
    ):
        [verdict] = await run(
            [Group(id="test/settle", run=script)], one, two, workdir=tmp_path / "run"
        )

    assert verdict.outcome is Outcome.MATCH
    assert played == [one.endpoint.port, two.endpoint.port]
