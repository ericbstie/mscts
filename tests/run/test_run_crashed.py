"""A launched Instance that crashes in one Group changes no later Group's Verdict (#531).

The fakes are control_fake.py processes, which a Group's Control joins. One given `CRASHES`
exits when it is asked to step its frozen world, as Pumpkin b70c7e1 exits when it panics in its
player-data save: every connection is lost, and the world cannot be unfrozen.
"""

import dataclasses
import functools
from collections.abc import Callable
from pathlib import Path

import pytest

from mscts import run as run_module
from mscts.compare import Outcome
from mscts.group import Group, GroupContext, GroupKind
from mscts.groups import status
from mscts.run import Server, run, run_results
from tests.run.fakes import FakeAdapter, attached

type MakeServer = Callable[..., Server]

CRASHES = ("crash", "tick step 1")
"""control_fake.py's options for a fake that exits when its frozen world is stepped."""

LOST = "could not be reached to unfreeze its world: ConnectionClosedError: "
"""How the Run says why it restarted an Instance that crashed in a frozen world."""


async def _crashes(context: GroupContext) -> None:
    await context.freeze()
    await context.step()


async def _crashes_sampled(context: GroupContext) -> None:
    await _crashes(context)
    context.sample("x", 1.0)


async def _stays_frozen(context: GroupContext) -> None:
    await context.freeze()


CRASH = Group(id="test/crash", run=_crashes, kind=GroupKind.TICK_EXACT)
CRASH_SAMPLED = Group(
    id="test/crash-sampled", run=_crashes_sampled, kind=GroupKind.STATISTICAL, runs=1
)
STAYS_FROZEN = Group(id="test/stays-frozen", run=_stays_frozen, kind=GroupKind.TICK_EXACT)
BASIC = Group(id="status/basic", run=status.basic)


def _adapter(server: Server) -> FakeAdapter:
    assert isinstance(server.adapter, FakeAdapter)
    return server.adapter


@pytest.fixture
def playing(fake_server: MakeServer) -> MakeServer:
    """Make a Server named `name` whose Instances are control_fake.py processes given `options`."""

    def make(name: str, options: tuple[str, ...] = ()) -> Server:
        server = fake_server(name)
        adapter = dataclasses.replace(_adapter(server), plays=options)
        return dataclasses.replace(server, adapter=adapter)

    return make


@pytest.mark.asyncio
async def test_the_group_a_launched_candidate_crashed_in_is_its_mismatch(
    playing: MakeServer, tmp_path: Path
) -> None:
    reference, candidate = playing("one"), playing("two", CRASHES)

    crashed, _ = await run([CRASH, BASIC], reference, candidate, workdir=tmp_path / "run")

    assert crashed.outcome is Outcome.MISMATCH, crashed
    assert [(d.kind, d.bot) for d in crashed.divergences] == [("failed", "control")], crashed
    assert str(crashed.divergences[0].candidate).startswith("ConnectionClosedError: "), crashed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("group", "crashes"),
    [(CRASH, CRASHES), (CRASH_SAMPLED, CRASHES), (STAYS_FROZEN, ("crash", "tick unfreeze"))],
    ids=["tick-exact", "statistical", "at-the-unfreeze"],
)
async def test_the_group_after_a_crash_plays_on_a_new_pair_and_gets_its_own_verdict(
    group: Group, crashes: tuple[str, ...], playing: MakeServer, tmp_path: Path
) -> None:
    # At the unfreeze, the Group's end raises (GroupContext.end), not its close.
    reference, candidate = playing("one"), playing("two", crashes)

    _, after = await run([group, BASIC], reference, candidate, workdir=tmp_path / "run")

    assert (after.outcome, after.detail) == (Outcome.MATCH, ""), after
    assert len(_adapter(reference).prepared) == len(_adapter(candidate).prepared) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("crashed", ["reference", "candidate"])
async def test_the_run_records_the_restart_after_the_group_the_side_crashed_in(
    crashed: str, playing: MakeServer, tmp_path: Path
) -> None:
    sides = {
        role: playing(role, CRASHES if role == crashed else ())
        for role in ("reference", "candidate")
    }

    result = await run_results([CRASH, BASIC], *sides.values(), workdir=tmp_path / "run")

    summaries = {"reference": result.reference, "candidate": result.candidate}
    [restart] = summaries.pop(crashed).restarts
    assert restart.after == CRASH.id
    assert restart.reason.startswith(LOST), restart
    assert [summary.restarts for summary in summaries.values()] == [()]
    assert result.verdicts[1].outcome is Outcome.MATCH, result.verdicts


@pytest.mark.asyncio
async def test_an_attached_candidate_that_crashed_fails_each_later_group(
    playing: MakeServer, run_token: str, tmp_path: Path
) -> None:
    # An Attached Instance is not the Run's to restart (#228).
    reference = playing("one")
    adapter = FakeAdapter(name="two", token=run_token, plays=CRASHES)

    async with attached(adapter, tmp_path) as candidate:
        verdicts = await run(
            [CRASH, BASIC], reference, candidate, workdir=tmp_path / "run", repeat=2
        )

    what = f"{CRASH.id} left its world frozen"
    assert [(verdict.outcome, verdict.detail) for verdict in verdicts[1:]] == [
        (Outcome.MISMATCH, f"the Candidate failed: {what}")
    ] * 3
    assert len(_adapter(reference).prepared) == 1


REFUSE_LIMIT_S = 2.0
"""Each Bot operation's bound in the test of a refused unfreeze, which only the refusal reaches."""


@pytest.mark.asyncio
async def test_a_launched_candidate_that_answers_and_will_not_unfreeze_stays_unusable(
    playing: MakeServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Its unfreeze times out, and it still answers a status request: no connection was
    # lost, so it is unusable, as an Attached one is (#228).
    run_group = functools.partial(run_module.run_group, timeout_s=REFUSE_LIMIT_S)
    monkeypatch.setattr(run_module, "run_group", run_group)
    reference = playing("one")
    candidate = playing("two", ("refuse", "tick unfreeze"))

    result = await run_results(
        [STAYS_FROZEN, BASIC], reference, candidate, workdir=tmp_path / "run"
    )

    after = result.verdicts[1]
    what = f"{STAYS_FROZEN.id} left its world frozen"
    assert (after.outcome, after.detail) == (Outcome.MISMATCH, f"the Candidate failed: {what}")
    assert result.candidate.restarts == result.reference.restarts == ()
    assert len(_adapter(candidate).prepared) == 1
