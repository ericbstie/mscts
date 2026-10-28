"""A launched Instance that keeps a player online after a Group changes no later Verdict (#513).

The fakes keep `crafter` online after they pong a ping of `LINGERS` (status_fake.py), as
Pumpkin does after a Ctrl+Q over a crafting result: it answers a status request, but the
player of a Bot that left is never removed.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from mscts import run as run_module
from mscts.compare import Outcome, Verdict
from mscts.group import Group, GroupContext, GroupKind
from mscts.groups import status
from mscts.net import Endpoint
from mscts.run import Restart, Server, run_results
from mscts.settle import PlayersStillOnline
from tests.run.fakes import FakeAdapter, attached

LINGERS = 266
"""The ping payload after which a fake made with `lingers_after_ping=LINGERS` keeps a player."""

HANGS = 513
"""The ping payload after which a fake made with `hangs_after_ping=HANGS` hangs."""

SHORT_S = 0.3
"""The wait for no player online here: short, so the tests stay fast."""

LONG_S = 1.0
"""A wait for no player online longer than any play here takes."""

type MakeServer = Callable[..., Server]


async def _lingers(context: GroupContext) -> None:
    bot = await context.bot("status")
    await bot.ping(LINGERS)


async def _lingers_sampled(context: GroupContext) -> None:
    await _lingers(context)
    context.sample("x", 1.0)


async def _hangs(context: GroupContext) -> None:
    bot = await context.bot("status")
    await bot.ping(HANGS)


LINGER = Group(id="test/linger", run=_lingers)
LINGER_SAMPLED = Group(
    id="test/linger-sampled", run=_lingers_sampled, kind=GroupKind.STATISTICAL, runs=1
)
HANG = Group(id="test/hang", run=_hangs)
BASIC = Group(id="status/basic", run=status.basic)
BASIC_AGAIN = Group(id="test/basic-again", run=status.basic)

ONLINE = f"1 player still online after waiting {SHORT_S:g} s: 'crafter'"
"""What a fake that keeps its player is found to have, once `SHORT_S` has passed."""


def _adapter(server: Server) -> FakeAdapter:
    assert isinstance(server.adapter, FakeAdapter)
    return server.adapter


@pytest.fixture(autouse=True)
def _short_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_module, "SETTLE_TIMEOUT_S", SHORT_S)


@pytest.mark.asyncio
async def test_a_group_that_leaves_a_player_on_the_candidate_fails_and_the_next_plays_anew(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    reference, candidate = fake_server("one"), fake_server("two", lingers_after_ping=LINGERS)

    result = await run_results([LINGER, BASIC], reference, candidate, workdir=tmp_path / "run")

    left, after = result.verdicts
    assert left.outcome is Outcome.MISMATCH, left
    what = f"after the Group, {ONLINE}"
    assert [divergence.candidate for divergence in left.divergences] == [what]
    assert left.detail == f"the Candidate failed: {what}"
    assert left.test_cases == ("status:pong_response.timestamp",)
    assert after.outcome is Outcome.MATCH, after
    assert len(_adapter(reference).prepared) == len(_adapter(candidate).prepared) == 2


@pytest.mark.asyncio
async def test_the_run_says_it_restarted_the_candidate_after_the_group_that_left_a_player(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    reference, candidate = fake_server("one"), fake_server("two", lingers_after_ping=LINGERS)

    result = await run_results([LINGER, BASIC], reference, candidate, workdir=tmp_path / "run")

    assert result.candidate.restarts == (Restart(after="test/linger", reason=f"had {ONLINE}"),)
    assert result.reference.restarts == ()


@pytest.mark.asyncio
async def test_a_reference_that_keeps_a_player_after_a_group_makes_it_an_error(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    # As a Reference with a player online before a Group is (#266); the pair is restarted.
    reference, candidate = fake_server("one", lingers_after_ping=LINGERS), fake_server("two")

    result = await run_results([LINGER, BASIC], reference, candidate, workdir=tmp_path / "run")

    left, after = result.verdicts
    assert left == Verdict(
        "test/linger", Outcome.ERROR, detail=f"after the Group, the Reference had {ONLINE}"
    )
    assert after.outcome is Outcome.MATCH, after
    assert result.reference.restarts == (Restart(after="test/linger", reason=f"had {ONLINE}"),)
    assert result.candidate.restarts == ()
    assert len(_adapter(reference).prepared) == len(_adapter(candidate).prepared) == 2


@pytest.mark.asyncio
async def test_both_sides_that_keep_a_player_are_both_named(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    reference = fake_server("one", lingers_after_ping=LINGERS)
    candidate = fake_server("two", lingers_after_ping=LINGERS)

    result = await run_results([LINGER, BASIC], reference, candidate, workdir=tmp_path / "run")

    left, after = result.verdicts
    both = f"after the Group, the Reference had {ONLINE}; the Candidate had {ONLINE}"
    assert left == Verdict("test/linger", Outcome.ERROR, detail=both)
    assert after.outcome is Outcome.MATCH, after
    assert len(result.reference.restarts) == len(result.candidate.restarts) == 1


@pytest.mark.asyncio
async def test_a_candidate_that_keeps_a_player_after_a_statistical_group_fails_it(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    reference, candidate = fake_server("one"), fake_server("two", lingers_after_ping=LINGERS)

    [left] = (
        await run_results([LINGER_SAMPLED], reference, candidate, workdir=tmp_path / "run")
    ).verdicts

    assert left.outcome is Outcome.MISMATCH, left
    assert [divergence.candidate for divergence in left.divergences] == [
        f"after the Group, {ONLINE}"
    ]


@pytest.mark.asyncio
async def test_a_reference_that_plays_alone_and_keeps_a_player_makes_the_group_an_error(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    # The Candidate hangs in test/hang and cannot be started again, so the Reference plays alone.
    reference = fake_server("one", lingers_after_ping=LINGERS)
    candidate = fake_server("two", hangs_after_ping=HANGS, fails_launch=frozenset({2}))
    groups = [HANG, LINGER, LINGER_SAMPLED]

    result = await run_results(groups, reference, candidate, workdir=tmp_path / "run")

    _, left, sampled = result.verdicts
    detail = f"after the Group, the Reference had {ONLINE}"
    assert left == Verdict("test/linger", Outcome.ERROR, detail=detail)
    assert sampled == Verdict("test/linger-sampled", Outcome.ERROR, detail=detail)
    assert len(_adapter(reference).prepared) == 3


@pytest.mark.asyncio
async def test_the_wait_after_a_group_is_no_part_of_its_time(
    fake_server: MakeServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_module, "SETTLE_TIMEOUT_S", LONG_S)
    reference, candidate = fake_server("one"), fake_server("two", lingers_after_ping=LINGERS)

    result = await run_results([LINGER], reference, candidate, workdir=tmp_path / "run")

    assert result.verdicts[0].outcome is Outcome.MISMATCH
    [elapsed_s] = result.results[0].elapsed_s
    assert elapsed_s < LONG_S, "the Group's time includes the wait for no player online"


@pytest.mark.asyncio
async def test_an_instance_that_did_not_answer_is_not_waited_on_after_the_group(
    fake_server: MakeServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # It is restarted anyway, and a wait on a hung server costs up to SETTLE_TIMEOUT_S.
    waited: list[Endpoint] = []

    async def until_answered_no_player_online(endpoint: Endpoint, *, deadline_s: float) -> None:
        del deadline_s
        waited.append(endpoint)

    monkeypatch.setattr(run_module, "ANSWER_TIMEOUT_S", SHORT_S)
    monkeypatch.setattr(
        run_module, "until_answered_no_player_online", until_answered_no_player_online
    )
    reference, candidate = fake_server("one"), fake_server("two", hangs_after_ping=HANGS)

    await run_results([HANG], reference, candidate, workdir=tmp_path / "run")

    assert len(waited) == 1, waited


@pytest.mark.asyncio
async def test_a_status_with_no_answer_in_the_wait_after_a_group_restarts_the_pair(
    fake_server: MakeServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The Candidate answers the status request after test/hang, and hangs just after it
    # (review A1). The wait gets no answer, so nothing tells whether a player is still on.
    asked: list[Endpoint] = []
    answers = run_module._answers  # noqa: SLF001

    async def answered_once_each(endpoint: Endpoint, *, timeout_s: float) -> bool:
        first = endpoint not in asked
        asked.append(endpoint)
        return first or await answers(endpoint, timeout_s=timeout_s)

    monkeypatch.setattr(run_module, "_answers", answered_once_each)
    reference, candidate = fake_server("one"), fake_server("two", hangs_after_ping=HANGS)

    result = await run_results([HANG, BASIC], reference, candidate, workdir=tmp_path / "run")

    hang, after = result.verdicts
    assert hang.outcome is Outcome.MATCH, hang  # it answered once: no failure is proven
    assert after.outcome is Outcome.MATCH, after
    why = (
        f"did not answer a status request within {SHORT_S:g} s"
        " while mscts waited for its players to leave"
    )
    assert result.candidate.restarts == (Restart(after="test/hang", reason=why),)
    assert result.reference.restarts == ()


async def _missed(endpoint: Endpoint, *, deadline_s: float) -> None:
    """A wait after a Group that sees no player: one its status lists only later (review A2)."""
    del endpoint, deadline_s


@pytest.mark.asyncio
async def test_a_launched_candidate_with_a_player_before_a_group_fails_it_and_is_restarted(
    fake_server: MakeServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_module, "until_answered_no_player_online", _missed)
    reference, candidate = fake_server("one"), fake_server("two", lingers_after_ping=LINGERS)
    groups = [LINGER, BASIC, BASIC_AGAIN]

    result = await run_results(groups, reference, candidate, workdir=tmp_path / "run")

    left, before, after = result.verdicts
    assert left.outcome is Outcome.MATCH, left
    assert before.outcome is Outcome.MISMATCH, before
    assert before.detail == f"the Candidate failed: {ONLINE}"
    assert after.outcome is Outcome.MATCH, after
    assert result.candidate.restarts == (Restart(after="status/basic", reason=f"had {ONLINE}"),)
    assert result.reference.restarts == ()


@pytest.mark.asyncio
async def test_a_launched_reference_with_a_player_before_a_group_is_restarted_after_it(
    fake_server: MakeServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_module, "until_answered_no_player_online", _missed)
    reference, candidate = fake_server("one", lingers_after_ping=LINGERS), fake_server("two")
    groups = [LINGER, BASIC, BASIC_AGAIN]

    result = await run_results(groups, reference, candidate, workdir=tmp_path / "run")

    _, before, after = result.verdicts
    assert before == Verdict("status/basic", Outcome.ERROR, detail=f"the Reference had {ONLINE}")
    assert after.outcome is Outcome.MATCH, after
    assert result.reference.restarts == (Restart(after="status/basic", reason=f"had {ONLINE}"),)
    assert result.candidate.restarts == ()


@pytest.mark.asyncio
async def test_an_attached_candidate_that_keeps_a_player_fails_the_next_group_as_before(
    fake_server: MakeServer, run_token: str, tmp_path: Path
) -> None:
    # The Run did not launch it, so it is not the Run's to restart (#266 holds there).
    lingers = FakeAdapter("two", run_token, lingers_after_ping=LINGERS)
    reference = fake_server("one")
    async with attached(lingers, tmp_path / "two") as candidate:
        result = await run_results([LINGER, BASIC], reference, candidate, workdir=tmp_path / "run")

    left, after = result.verdicts
    assert left.outcome is Outcome.MATCH, left
    assert after.outcome is Outcome.MISMATCH, after
    assert [divergence.candidate for divergence in after.divergences] == [ONLINE]
    assert after.detail == f"the Candidate failed: {ONLINE}"
    assert result.candidate.restarts == result.reference.restarts == ()
    assert len(_adapter(reference).prepared) == 1


def test_an_error_stays_as_it_is_whichever_side_kept_a_player() -> None:
    error = Verdict("test/linger", Outcome.ERROR, detail="the Reference failed: TimeoutError")
    online = PlayersStillOnline(1, ["crafter"], SHORT_S)

    for left in ({0: online}, {1: online}, {0: online, 1: online}):
        assert run_module._left_online_verdict(error, left) is error  # noqa: SLF001


def test_a_candidate_that_had_failed_already_keeps_its_first_failure_as_the_detail() -> None:
    failed = run_module._failed(bot="crafter", what="ConnectionClosedError")  # noqa: SLF001
    first = Verdict("test/linger", Outcome.MISMATCH, (failed,), "the Candidate failed: Conn")
    online = PlayersStillOnline(1, ["crafter"], SHORT_S)

    verdict = run_module._left_online_verdict(first, {1: online})  # noqa: SLF001

    assert verdict.detail == "the Candidate failed: Conn"
    assert [divergence.candidate for divergence in verdict.divergences] == [
        "ConnectionClosedError",
        f"after the Group, {ONLINE}",
    ]


def test_a_wait_that_raised_anything_else_after_the_group_says_what_it_raised() -> None:
    # As the wait before a Group says it (#222).
    match = Verdict("test/linger", Outcome.MATCH)
    raised = RuntimeError("an unexpected failure")
    what = "the wait for no player online failed: RuntimeError: an unexpected failure"

    candidate = run_module._left_online_verdict(match, {1: raised})  # noqa: SLF001
    reference = run_module._left_online_verdict(match, {0: raised})  # noqa: SLF001

    assert [divergence.candidate for divergence in candidate.divergences] == [
        f"after the Group, {what}"
    ]
    assert reference.detail == f"after the Group, the Reference failed: {what}"
