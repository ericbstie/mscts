import json

import pytest

import mscts.compare
from mscts.codec.packets import Codec, Direction, Packet, State
from mscts.compare import ABSENT, Divergence, Observability, Outcome, Verdict, compare
from mscts.group import CommandMissing, Group, GroupContext
from mscts.groups import status
from mscts.run import GroupError, blocked, judge, run_group
from mscts.target import TARGET
from mscts.transcript import Transcript
from tests.net.fakes import VANILLA_STATUS, Handler, Peer, serve, status_server

BASIC = Group(id="status/basic", run=status.basic)
PING = Group(id="status/ping", run=status.ping, requires=("status/basic",))


async def _attempt(
    group: Group, handler: Handler, *, server: str = "fake"
) -> Transcript | GroupError:
    """Run `group` against a fake server running `handler`; its Transcript, or its error.

    The error is caught inside `serve`, which would otherwise replace its cause.
    """
    async with serve(Codec.for_target(TARGET), handler) as endpoint:
        try:
            return await run_group(group, endpoint, server=server, timeout_s=1.0)
        except GroupError as error:
            return error


async def _against(group: Group, json_response: str, *, server: str = "fake") -> Transcript:
    transcript = await _attempt(group, status_server(json_response, []), server=server)
    assert isinstance(transcript, Transcript)
    return transcript


def _vanilla() -> str:
    return json.dumps(VANILLA_STATUS)


@pytest.mark.asyncio
async def test_run_group_returns_the_transcript_of_one_instance() -> None:
    transcript = await _against(PING, _vanilla(), server="vanilla")

    assert (transcript.group_id, transcript.server) == ("status/ping", "vanilla")
    assert [event.packet.name for event in transcript.events][-1] == "minecraft:pong_response"
    assert [mark.label for mark in transcript.marks] == ["status.rtt:start", "status.rtt:end"]


@pytest.mark.asyncio
async def test_a_group_that_raises_is_a_group_error_holding_what_was_recorded() -> None:
    async def status_then_fail(context: GroupContext) -> None:
        await status.basic(context)
        msg = "the script broke"
        raise ProcessLookupError(msg)

    error = await _attempt(
        Group(id="test/broken", run=status_then_fail), status_server(_vanilla(), [])
    )

    assert isinstance(error, GroupError)
    assert isinstance(error.__cause__, ProcessLookupError)
    assert str(error) == "ProcessLookupError: the script broke"
    assert error.transcript.group_id == "test/broken"
    names = [event.packet.name for event in error.transcript.events]
    assert names[-1] == "minecraft:status_response"


@pytest.mark.asyncio
async def test_a_group_error_closes_the_bots_it_opened() -> None:
    closed: list[bool] = []

    async def wait_for_eof(peer: Peer) -> None:
        await peer.eof()
        closed.append(True)

    async def connect_then_fail(context: GroupContext) -> None:
        await context.bot("status")
        raise ProcessLookupError

    async with serve(Codec.for_target(TARGET), wait_for_eof) as endpoint:
        with pytest.raises(GroupError):
            await run_group(
                Group(id="test/x", run=connect_then_fail), endpoint, server="f", timeout_s=1.0
            )

    assert closed == [True]


@pytest.mark.asyncio
async def test_equal_transcripts_are_a_match() -> None:
    reference = await _against(BASIC, _vanilla())
    candidate = await _against(BASIC, _vanilla())

    verdict = judge(BASIC, reference, candidate)
    assert (verdict.group_id, verdict.outcome, verdict.divergences) == (
        "status/basic",
        Outcome.MATCH,
        (),
    )
    assert "status_response.players.max" in verdict.test_cases


@pytest.mark.asyncio
async def test_different_transcripts_are_a_mismatch_with_their_divergences() -> None:
    reference = await _against(BASIC, _vanilla())
    candidate = await _against(BASIC, json.dumps({**VANILLA_STATUS, "description": "other"}))

    verdict = judge(BASIC, reference, candidate)

    assert verdict.outcome is Outcome.MISMATCH
    [divergence] = verdict.divergences
    assert divergence.path == "json_response.description.text"
    assert (divergence.reference, divergence.candidate) == ("mscts", "other")


@pytest.mark.asyncio
async def test_a_reference_that_fails_is_an_error_naming_it() -> None:
    reference = GroupError(Transcript("status/basic", "vanilla"), "TimeoutError: no answer")
    candidate = await _against(BASIC, _vanilla())

    verdict = judge(BASIC, reference, candidate)

    assert verdict.outcome is Outcome.ERROR
    assert verdict.divergences == ()
    assert verdict.detail == "the Reference failed: TimeoutError: no answer"


def _odd(server: str) -> Transcript:
    """A Transcript holding a value the Comparison cannot take: it raises on it."""
    odd = Packet(
        state=State.STATUS,
        direction=Direction.CLIENTBOUND,
        name="minecraft:status_response",
        packet_id=0,
        payload=b"",
        fields={"json_response": {1, 2}},  # outside the codec value model
    )
    transcript = Transcript("status/basic", server)
    transcript.record("status", odd, t_ns=0)
    return transcript


def test_a_comparison_the_harness_cannot_make_is_an_error() -> None:
    verdict = judge(BASIC, _odd("vanilla"), Transcript("status/basic", "fake"))

    assert verdict.outcome is Outcome.ERROR
    assert verdict.detail.startswith("the Comparison failed: TypeError: ")


@pytest.mark.asyncio
async def test_a_candidate_value_the_comparison_cannot_take_is_a_mismatch_naming_it() -> None:
    reference = await _against(BASIC, _vanilla(), server="vanilla")

    verdict = judge(BASIC, reference, _odd("fake"))

    assert verdict.outcome is Outcome.MISMATCH
    [failed] = verdict.divergences
    assert (failed.kind, failed.bot, failed.test_case) == ("failed", "", "")
    assert isinstance(failed.candidate, str)
    assert failed.candidate.startswith("the Comparison failed: TypeError: ")
    assert verdict.detail == f"the Candidate failed: {failed.candidate}"
    # Each test case the Reference's play has is the Candidate's too, failed (#262).
    assert verdict.test_cases == compare(reference, reference, ()).test_cases
    assert verdict.test_cases


@pytest.mark.asyncio
async def test_a_candidate_that_raised_and_sent_a_value_the_comparison_cannot_take_says_both() -> (
    None
):
    reference = await _against(BASIC, _vanilla(), server="vanilla")
    candidate = GroupError(_odd("fake"), "TimeoutError: no answer", bot="status")

    verdict = judge(BASIC, reference, candidate)

    assert verdict.outcome is Outcome.MISMATCH
    raised, comparison = verdict.divergences
    assert (raised.kind, raised.bot, raised.candidate) == ("failed", "status", str(candidate))
    assert (comparison.kind, comparison.bot) == ("failed", "")
    assert str(comparison.candidate).startswith("the Comparison failed: TypeError: ")
    assert verdict.detail == f"the Candidate failed: {candidate}"
    assert verdict.test_cases == compare(reference, reference, ()).test_cases


@pytest.mark.asyncio
async def test_a_command_missing_with_a_value_the_comparison_cannot_take_names_the_command() -> (
    None
):
    reference = await _against(BASIC, _vanilla(), server="vanilla")
    candidate = GroupError(_odd("fake"), "CommandMissing: the server has no /tick command")
    candidate.__cause__ = CommandMissing("tick")

    verdict = judge(BASIC, reference, candidate)

    raised, comparison = verdict.divergences
    assert raised.candidate == "missing /tick"
    assert str(comparison.candidate).startswith("the Comparison failed: TypeError: ")
    assert verdict.detail == "the Candidate failed: missing /tick"


def test_a_group_whose_prerequisite_matched_is_not_blocked() -> None:
    assert blocked(PING, {"status/basic": Verdict("status/basic", Outcome.MATCH)}) is None


@pytest.mark.parametrize("outcome", [Outcome.MISMATCH, Outcome.BLOCKED, Outcome.ERROR])
def test_a_group_whose_prerequisite_did_not_match_is_blocked(outcome: Outcome) -> None:
    verdict = blocked(PING, {"status/basic": Verdict("status/basic", outcome)})

    assert verdict == Verdict(
        "status/ping", Outcome.BLOCKED, detail=f"prerequisite status/basic was {outcome}"
    )


def _sample(observability: Observability) -> Divergence:
    """Pumpkin's `players.sample: []`, where vanilla leaves it out."""
    return Divergence(
        bot="status",
        index=0,
        kind="field",
        packet="minecraft:status_response",
        path="players.sample",
        reference=ABSENT,
        candidate=[],
        test_case="status_response.players.sample",
        observability=observability,
    )


def test_a_prerequisite_that_differs_only_in_network_traffic_does_not_block() -> None:
    # #221: the Score counts its test cases as passing (ADR-0007), so it passed.
    differs = (_sample(Observability.NETWORK_TRAFFIC),)
    basic = Verdict("status/basic", Outcome.MISMATCH, differs)

    assert blocked(PING, {"status/basic": basic}) is None


def test_a_network_traffic_prerequisite_blocks_if_network_traffic_does_not_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The one switch for ADR-0007's rule decides blocking as it decides the Score.
    monkeypatch.setattr(mscts.compare, "NETWORK_TRAFFIC_ONLY_PASSES", False)
    differs = (_sample(Observability.NETWORK_TRAFFIC),)
    basic = Verdict("status/basic", Outcome.MISMATCH, differs)

    verdict = blocked(PING, {"status/basic": basic})

    assert verdict == Verdict(
        "status/ping", Outcome.BLOCKED, detail="prerequisite status/basic was mismatch"
    )


@pytest.mark.parametrize("outcome", [Outcome.BLOCKED, Outcome.ERROR])
def test_a_prerequisite_that_did_not_compare_blocks_whatever_its_divergences(
    outcome: Outcome,
) -> None:
    differs = (_sample(Observability.NETWORK_TRAFFIC),)
    basic = Verdict("status/basic", outcome, differs)

    verdict = blocked(PING, {"status/basic": basic})

    assert verdict == Verdict(
        "status/ping", Outcome.BLOCKED, detail=f"prerequisite status/basic was {outcome}"
    )


def test_a_prerequisite_with_a_gameplay_difference_too_blocks() -> None:
    differs = (_sample(Observability.NETWORK_TRAFFIC), _sample(Observability.GAMEPLAY))
    basic = Verdict("status/basic", Outcome.MISMATCH, differs)

    verdict = blocked(PING, {"status/basic": basic})

    assert verdict == Verdict(
        "status/ping", Outcome.BLOCKED, detail="prerequisite status/basic was mismatch"
    )


def test_a_group_whose_prerequisite_did_not_run_is_blocked() -> None:
    verdict = blocked(PING, {})

    assert verdict == Verdict(
        "status/ping", Outcome.BLOCKED, detail="prerequisite status/basic was not run"
    )
