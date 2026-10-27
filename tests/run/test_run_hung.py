"""An Instance that hangs in one Group changes no later Group's Verdict (#513).

The fakes hang after they pong a ping of `HANGS` (status_fake.py), as Pumpkin hangs on a
Ctrl+Q over a crafting result: the process runs and accepts connections, but never answers.
"""

import json
import logging
from collections.abc import Callable
from pathlib import Path

import pytest

from mscts import run as run_module
from mscts.codec.packets import Codec
from mscts.compare import Outcome, Verdict
from mscts.group import Group, GroupContext
from mscts.groups import status
from mscts.run import Restart, Server, run, run_results
from mscts.target import TARGET
from tests.net.fakes import VANILLA_STATUS, serve, status_server
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
async def test_a_group_after_one_that_hung_the_candidate_plays_on_a_new_pair(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    # Both sides start again, so the two worlds keep the same history (review B3).
    reference, candidate = fake_server("one"), fake_server("two", hangs_after_ping=HANGS)

    verdicts = await run([HANG, BASIC], reference, candidate, workdir=tmp_path / "run")

    assert verdicts[1].outcome is Outcome.MATCH, verdicts
    assert len(_adapter(reference).prepared) == 2
    assert len(_adapter(candidate).prepared) == 2


NO_ANSWER = f"no answer to a status request within {SHORT_S:g} s after the Group"
"""What a side that did not answer after it played `HANG` is said to have done."""


@pytest.mark.asyncio
async def test_a_candidate_that_does_not_answer_after_a_group_fails_that_group(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    # Its Transcript is complete, as the fake hangs only after its last pong (review B1).
    reference, candidate = fake_server("one"), fake_server("two", hangs_after_ping=HANGS)

    hung, _ = await run([HANG, BASIC], reference, candidate, workdir=tmp_path / "run")

    assert hung.outcome is Outcome.MISMATCH, hung
    assert [divergence.candidate for divergence in hung.divergences] == [NO_ANSWER]
    assert hung.detail == f"the Candidate failed: {NO_ANSWER}"
    assert hung.test_cases == ("status:pong_response.timestamp",)


@pytest.mark.asyncio
async def test_a_reference_that_does_not_answer_after_a_group_makes_it_an_error(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    reference, candidate = fake_server("one", hangs_after_ping=HANGS), fake_server("two")

    hung, after = await run([HANG, BASIC], reference, candidate, workdir=tmp_path / "run")

    assert hung == Verdict("test/hang", Outcome.ERROR, detail=f"the Reference gave {NO_ANSWER}")
    assert after.outcome is Outcome.MATCH, after


@pytest.mark.asyncio
async def test_both_sides_that_do_not_answer_are_both_named(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    reference = fake_server("one", hangs_after_ping=HANGS)
    candidate = fake_server("two", hangs_after_ping=HANGS)

    result = await run_results([HANG, BASIC], reference, candidate, workdir=tmp_path / "run")

    hung, after = result.verdicts
    both = f"the Reference gave {NO_ANSWER}; the Candidate gave {NO_ANSWER}"
    assert hung == Verdict("test/hang", Outcome.ERROR, detail=both)
    assert after.outcome is Outcome.MATCH, after
    assert len(result.reference.restarts) == len(result.candidate.restarts) == 1
    assert {path.name for path in (tmp_path / "run").iterdir()} == {"0", "restart-1"}


def test_an_error_stays_as_it_is_whichever_side_did_not_answer() -> None:
    error = Verdict("test/hang", Outcome.ERROR, detail="the Reference failed: TimeoutError")

    for silent in ({0}, {1}, {0, 1}):
        assert run_module._unanswered_verdict(error, silent, timeout_s=SHORT_S) is error  # noqa: SLF001


def test_a_candidate_that_had_failed_already_keeps_its_first_failure_as_the_detail() -> None:
    failed = run_module._failed(bot="crafter", what="ConnectionClosedError")  # noqa: SLF001
    first = Verdict("test/hang", Outcome.MISMATCH, (failed,), "the Candidate failed: Conn")

    verdict = run_module._unanswered_verdict(first, {1}, timeout_s=SHORT_S)  # noqa: SLF001

    assert verdict.detail == "the Candidate failed: Conn"
    assert [divergence.candidate for divergence in verdict.divergences] == [
        "ConnectionClosedError",
        NO_ANSWER,
    ]


@pytest.mark.asyncio
async def test_the_run_says_which_side_it_restarted_after_which_group_and_why(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    reference, candidate = fake_server("one", hangs_after_ping=HANGS), fake_server("two")

    result = await run_results([HANG, BASIC], reference, candidate, workdir=tmp_path / "run")

    why = f"did not answer a status request within {SHORT_S} s"
    assert result.reference.restarts == (Restart(after="test/hang", reason=why),)
    assert result.candidate.restarts == ()
    assert result.verdicts[1].outcome is Outcome.MATCH


@pytest.mark.asyncio
async def test_each_restart_has_a_directory_of_its_own_and_its_wait_in_whole_seconds(
    fake_server: MakeServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_module, "ANSWER_TIMEOUT_S", 1.0)
    reference, candidate = fake_server("one"), fake_server("two", hangs_after_ping=HANGS)

    result = await run_results(
        [HANG, BASIC], reference, candidate, workdir=tmp_path / "run", repeat=2
    )

    hung = Restart(after="test/hang", reason="did not answer a status request within 1 s")
    assert result.candidate.restarts == (hung, hung)
    assert {path.name for path in (tmp_path / "run").iterdir()} == {"0", "restart-1", "restart-2"}
    assert (tmp_path / "run/restart-2/candidate").is_dir()
    assert (tmp_path / "run/restart-2/reference").is_dir()


@pytest.mark.asyncio
async def test_a_status_that_is_not_the_target_s_is_still_an_answer() -> None:
    # The server is not hung: the next Group shows what it sends, so it is not restarted.
    other = json.dumps({**VANILLA_STATUS, "version": {"name": "1.8", "protocol": 47}})

    async with serve(Codec.for_target(TARGET), status_server(other, [])) as endpoint:
        answered = await run_module._answers(endpoint, timeout_s=SHORT_S)  # noqa: SLF001 - the check alone

    assert answered is True


@pytest.mark.asyncio
async def test_both_instances_are_stopped_before_the_next_group_plays(
    fake_server: MakeServer, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    reference, candidate = fake_server("one"), fake_server("two", hangs_after_ping=HANGS)

    await run([HANG, BASIC], reference, candidate, workdir=tmp_path / "run")

    messages = [record.getMessage() for record in caplog.records]
    before = messages[: messages.index("running status/basic (1 of 1) ...")]
    assert sum(" stopped by " in message for message in before) == 2, messages
