"""An Instance that hangs in one Group changes no later Group's Verdict (#513).

The fakes hang after they pong a ping of `HANGS` (status_fake.py), as Pumpkin hangs on a
Ctrl+Q over a crafting result: the process runs and accepts connections, but never answers.
"""

import contextlib
import json
import logging
import select
import socket
from collections.abc import Callable
from pathlib import Path
from typing import override

import pytest

from mscts import run as run_module
from mscts.codec.packets import Codec
from mscts.compare import Outcome, Verdict
from mscts.group import Group, GroupContext, GroupKind
from mscts.groups import status
from mscts.net import Endpoint
from mscts.run import Restart, Server, run, run_results
from mscts.target import TARGET
from tests.net.fakes import VANILLA_STATUS, serve, status_server
from tests.run import status_fake
from tests.run.fakes import FakeAdapter

HANGS = 513
"""The ping payload after which a fake made with `hangs_after_ping=HANGS` hangs."""

SHORT_S = 0.3
"""The waits on a hung fake here: short, so the tests stay fast."""

type MakeServer = Callable[..., Server]


async def _hangs(context: GroupContext) -> None:
    bot = await context.bot("status")
    await bot.ping(HANGS)


async def _hangs_sampled(context: GroupContext) -> None:
    await _hangs(context)
    context.sample("x", 1.0)


HANG = Group(id="test/hang", run=_hangs)
BASIC = Group(id="status/basic", run=status.basic)
HANG_AGAIN = Group(id="test/hang-again", run=_hangs)
HANG_SAMPLED = Group(id="test/hang-sampled", run=_hangs_sampled, kind=GroupKind.STATISTICAL, runs=1)


def _pong_sent(client: socket.socket) -> bool:
    """Whether a pong waits to be read on `client`: the fake has sent it."""
    return bool(select.select([client], [], [], 0)[0])


class _WatchedHang(status_fake.Hang):
    """A Hang that notes whether the pong was sent when the ping hung it."""

    def __init__(self, after_ping: bytes, client: socket.socket) -> None:
        super().__init__(after_ping)
        self.client = client
        self.pong_sent: bool | None = None

    @override
    def pinged(self, payload: bytes) -> None:
        self.pong_sent = _pong_sent(self.client)
        super().pinged(payload)


class _WatchedStatus(status_fake.Status):
    """A Status that notes whether the pong was sent when the ping made a player linger."""

    def __init__(self, linger_after_ping: bytes, client: socket.socket) -> None:
        super().__init__("watched", linger_after_ping)
        self.client = client
        self.pong_sent: bool | None = None

    @override
    def pinged(self, payload: bytes) -> None:
        self.pong_sent = _pong_sent(self.client)
        super().pinged(payload)


def test_a_fake_hangs_and_keeps_a_player_before_it_sends_the_pong_that_makes_it() -> None:
    # A status ask made on seeing that pong must not be answered, however the fake is scheduled
    # (#524): a fake that sent the pong first could be asked before it had hung.
    client, served = socket.socketpair()
    ping = HANGS.to_bytes(8, "big", signed=True)
    hang, status = _WatchedHang(ping, client), _WatchedStatus(ping, client)

    with client:
        client.sendall(status_fake.frame(0, b"") + status_fake.frame(1, ping))
        status_fake.serve_one(served, status, hang)

    assert (hang.pong_sent, status.pong_sent) == (False, False)


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
async def test_a_candidate_that_does_not_answer_after_a_statistical_group_fails_it(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    reference, candidate = fake_server("one"), fake_server("two", hangs_after_ping=HANGS)

    [hung] = await run([HANG_SAMPLED], reference, candidate, workdir=tmp_path / "run")

    assert hung.outcome is Outcome.MISMATCH, hung
    assert [divergence.candidate for divergence in hung.divergences] == [NO_ANSWER]


@pytest.mark.asyncio
async def test_a_reference_that_plays_alone_and_does_not_answer_makes_the_group_an_error(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    # The Candidate cannot be started again after test/hang, so the Reference plays alone.
    reference = fake_server("one", hangs_after_ping=HANGS)
    candidate = fake_server("two", hangs_after_ping=HANGS, fails_launch=SECOND)
    groups = [HANG, HANG_AGAIN, HANG_SAMPLED]

    _, again, sampled = await run(groups, reference, candidate, workdir=tmp_path / "run")

    detail = f"the Reference gave {NO_ANSWER}"
    assert again == Verdict("test/hang-again", Outcome.ERROR, detail=detail)
    assert sampled == Verdict("test/hang-sampled", Outcome.ERROR, detail=detail)


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


SECOND = frozenset({2})
"""The launches of a fake that exit at once: its restart (review A1)."""

NOT_AGAIN = "could not be started again after test/hang: "
"""How a side whose restart failed is said to be unusable, before the RunnerError's reason."""


@pytest.mark.asyncio
async def test_a_candidate_that_cannot_be_started_again_fails_each_later_group(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    reference = fake_server("one")
    candidate = fake_server("two", hangs_after_ping=HANGS, fails_launch=SECOND)

    result = await run_results(
        [HANG, BASIC], reference, candidate, workdir=tmp_path / "run", repeat=2
    )

    _, basic, hung, again = result.verdicts
    assert basic.detail.startswith(f"the Candidate failed: {NOT_AGAIN}"), basic
    assert "exited with code 3 before it was ready" in basic.detail
    assert [basic.outcome, hung.outcome, again.outcome] == [Outcome.MISMATCH] * 3
    assert basic.detail == hung.detail == again.detail
    assert result.candidate.restarts == ()
    assert len(_adapter(candidate).prepared) == 2


@pytest.mark.asyncio
async def test_a_reference_that_cannot_be_started_again_makes_each_later_group_an_error(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    reference = fake_server("one", fails_launch=SECOND)
    candidate = fake_server("two", hangs_after_ping=HANGS)

    result = await run_results([HANG, BASIC], reference, candidate, workdir=tmp_path / "run")

    basic = result.verdicts[1]
    assert basic.outcome is Outcome.ERROR, basic
    assert basic.detail.startswith(f"the Reference is unusable: {NOT_AGAIN}"), basic
    why = f"did not answer a status request within {SHORT_S} s"
    assert result.candidate.restarts == (Restart(after="test/hang", reason=why),)


@pytest.mark.asyncio
async def test_a_side_that_could_not_be_started_again_is_not_started_at_the_next_restart(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    # Its third launch would work, but it stays unusable for the rest of the Run (#228).
    reference = fake_server("one", hangs_after_ping=HANGS)
    candidate = fake_server("two", hangs_after_ping=HANGS, fails_launch=SECOND)

    result = await run_results(
        [HANG, BASIC], reference, candidate, workdir=tmp_path / "run", repeat=2
    )

    assert result.verdicts[3].detail.startswith(f"the Candidate failed: {NOT_AGAIN}")
    assert len(_adapter(reference).prepared) == 3
    assert len(_adapter(candidate).prepared) == 2


@pytest.mark.asyncio
async def test_a_side_that_stays_where_it_was_at_a_restart_has_no_restart_recorded(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    # An unusable side (#228) is not launched again, even if it did not answer.
    async with contextlib.AsyncExitStack() as stack:
        sides = (fake_server("one"), fake_server("two"))
        instances = run_module._Instances(stack, *sides, tmp_path, keep_transcripts=False)  # noqa: SLF001
        old = Endpoint("127.1.2.3", 25565)
        hung = Restart(after="test/hang", reason="did not answer")

        stays = instances._relaunched(1, old, old, {1: hung})  # noqa: SLF001

    assert stays == old
    assert instances.summaries()[1].restarts == ()


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
