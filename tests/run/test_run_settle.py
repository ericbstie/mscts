"""A Run plays a Group only once the previous Group's Bots have left the server (#97).

`Bot.close()` only closes the socket, and a server removes the player later (vanilla on its
next tick). So before a Group plays on an Instance, the Run waits until the Instance's status
says no player is online (`mscts.settle`, tested in `test_settle.py`). The fakes here answer
each status request from a script of counts.
"""

import asyncio
from pathlib import Path
from time import perf_counter

import pytest

import mscts.run as run_module
import mscts.settle as settle_module
from mscts.compare import ABSENT, Divergence, Outcome, Verdict
from mscts.group import Group, GroupContext
from mscts.groups import status
from mscts.net import Endpoint
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


RAISED = "the wait for no player online failed: RuntimeError: an unexpected failure"
"""What a settle poll that raises RuntimeError comes to as a sentence."""


async def _play_with_a_raising_poll(
    raising: tuple[str, ...], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[list[Verdict], list[str]]:
    """Run two Groups, the first settle poll of each side in `raising` raising RuntimeError.

    Every poll of another side ends only after a while. Returns the Verdicts, and what
    happened in order: each poll ending ("<side> settled"), each Group played.
    """
    happened: list[str] = []
    raised: set[str] = set()

    async def poll(endpoint: Endpoint, *, deadline_s: float) -> None:
        del deadline_s
        side = names[endpoint.port]
        if side in raising and side not in raised:
            raised.add(side)
            msg = "an unexpected failure"
            raise RuntimeError(msg)
        if side not in raising:
            await asyncio.sleep(0.1)  # still polling when the other side raises
        happened.append(f"{side} settled")

    async def script(context: GroupContext) -> None:
        happened.append(f"{names[context.endpoint.port]} played")

    monkeypatch.setattr(run_module, "until_no_player_online", poll)
    async with (
        attached("one", never_answer) as one,
        attached("two", never_answer) as two,
    ):
        names = {one.endpoint.port: "Reference", two.endpoint.port: "Candidate"}
        verdicts = await run(
            [Group(id="test/first", run=script), Group(id="test/second", run=script)],
            one,
            two,
            workdir=tmp_path / "run",
        )
    return verdicts, happened


@pytest.mark.asyncio
async def test_a_candidate_whose_settle_poll_raises_gets_a_mismatch_and_the_run_goes_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    verdicts, happened = await _play_with_a_raising_poll(("Candidate",), monkeypatch, tmp_path)

    first, second = verdicts
    assert first == Verdict(
        group_id="test/first",
        outcome=Outcome.MISMATCH,
        divergences=(
            Divergence(
                bot="",
                index=0,
                kind="failed",
                packet="",
                path=None,
                reference=ABSENT,
                candidate=RAISED,
                test_case="",
            ),
        ),
        detail=f"the Candidate failed: {RAISED}",
    )
    assert second.outcome is Outcome.MATCH
    assert happened == [
        "Reference settled",  # the other poll ran to its end before the Run went on
        "Candidate settled",
        "Reference settled",
        "Reference played",
        "Candidate played",
    ]


@pytest.mark.asyncio
async def test_a_reference_whose_settle_poll_raises_gets_an_error_and_the_run_goes_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    verdicts, happened = await _play_with_a_raising_poll(("Reference",), monkeypatch, tmp_path)

    first, second = verdicts
    assert first == Verdict(
        group_id="test/first", outcome=Outcome.ERROR, detail=f"the Reference failed: {RAISED}"
    )
    assert second.outcome is Outcome.MATCH
    assert happened == [
        "Candidate settled",
        "Reference settled",
        "Candidate settled",
        "Reference played",
        "Candidate played",
    ]


@pytest.mark.asyncio
async def test_when_both_settle_polls_raise_the_error_says_what_each_raised(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    both = ("Reference", "Candidate")
    verdicts, _ = await _play_with_a_raising_poll(both, monkeypatch, tmp_path)

    detail = f"the Reference failed: {RAISED}; the Candidate failed: {RAISED}"
    assert verdicts[0] == Verdict(group_id="test/first", outcome=Outcome.ERROR, detail=detail)


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
