"""An Instance that hangs in one Group changes no later Group's Verdict (#513).

The fakes hang after they pong a ping of `HANGS` (status_fake.py), as Pumpkin hangs on a
Ctrl+Q over a crafting result: the process runs and accepts connections, but never answers.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from mscts import run as run_module
from mscts.compare import Outcome
from mscts.group import Group, GroupContext
from mscts.groups import status
from mscts.run import Restart, Server, run, run_results
from tests.run.fakes import FakeAdapter

HANGS = 513
"""The ping payload after which a fake made with `hangs_after_ping=HANGS` hangs."""

SHORT_S = 0.3
"""The waits on a hung fake here: short, so the tests stay fast."""

type MakeServer = Callable[..., Server]


async def _hangs(context: GroupContext) -> None:
    bot = await context.bot("status")
    await bot.ping(HANGS)


HANG = Group(id="test/hang", run=_hangs)
BASIC = Group(id="status/basic", run=status.basic)


def _adapter(server: Server) -> FakeAdapter:
    assert isinstance(server.adapter, FakeAdapter)
    return server.adapter


@pytest.fixture(autouse=True)
def _short_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_module, "SETTLE_TIMEOUT_S", SHORT_S)
    monkeypatch.setattr(run_module, "ANSWER_TIMEOUT_S", SHORT_S)


@pytest.mark.asyncio
async def test_a_group_after_one_that_hung_the_candidate_plays_on_a_new_instance(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    reference, candidate = fake_server("one"), fake_server("two", hangs_after_ping=HANGS)

    verdicts = await run([HANG, BASIC], reference, candidate, workdir=tmp_path / "run")

    assert [verdict.outcome for verdict in verdicts] == [Outcome.MATCH, Outcome.MATCH], verdicts
    assert len(_adapter(reference).prepared) == 1
    assert len(_adapter(candidate).prepared) == 2


@pytest.mark.asyncio
async def test_the_run_says_which_side_it_restarted_after_which_group_and_why(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    reference, candidate = fake_server("one", hangs_after_ping=HANGS), fake_server("two")

    result = await run_results([HANG, BASIC], reference, candidate, workdir=tmp_path / "run")

    why = f"did not answer a status request within {SHORT_S} s"
    assert result.reference.restarts == (Restart(after="test/hang", reason=why),)
    assert result.candidate.restarts == ()
    assert [verdict.outcome for verdict in result.verdicts] == [Outcome.MATCH, Outcome.MATCH]
