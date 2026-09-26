import json

import pytest

from mscts.codec.packets import Codec, Direction, Packet, State
from mscts.compare import Outcome, Verdict
from mscts.run import ScenarioError, blocked, judge, run_scenario
from mscts.scenario import Scenario, ScenarioContext
from mscts.scenarios import status
from mscts.target import TARGET
from mscts.transcript import Transcript
from tests.net.fakes import VANILLA_STATUS, Handler, Peer, serve, status_server

BASIC = Scenario(id="status/basic", run=status.basic)
PING = Scenario(id="status/ping", run=status.ping, requires=("status/basic",))


async def _attempt(
    scenario: Scenario, handler: Handler, *, server: str = "fake"
) -> Transcript | ScenarioError:
    """Run `scenario` against a fake server running `handler`; its Transcript, or its error.

    The error is caught inside `serve`, which would otherwise replace its cause.
    """
    async with serve(Codec.for_target(TARGET), handler) as endpoint:
        try:
            return await run_scenario(scenario, endpoint, server=server, timeout_s=1.0)
        except ScenarioError as error:
            return error


async def _against(scenario: Scenario, json_response: str, *, server: str = "fake") -> Transcript:
    transcript = await _attempt(scenario, status_server(json_response, []), server=server)
    assert isinstance(transcript, Transcript)
    return transcript


def _vanilla() -> str:
    return json.dumps(VANILLA_STATUS)


@pytest.mark.asyncio
async def test_run_scenario_returns_the_transcript_of_one_instance() -> None:
    transcript = await _against(PING, _vanilla(), server="vanilla")

    assert (transcript.scenario_id, transcript.server) == ("status/ping", "vanilla")
    assert [event.packet.name for event in transcript.events][-1] == "minecraft:pong_response"
    assert [mark.label for mark in transcript.marks] == ["status.rtt:start", "status.rtt:end"]


@pytest.mark.asyncio
async def test_a_scenario_that_raises_is_a_scenario_error_holding_what_was_recorded() -> None:
    async def status_then_fail(context: ScenarioContext) -> None:
        await status.basic(context)
        msg = "the script broke"
        raise ProcessLookupError(msg)

    error = await _attempt(
        Scenario(id="test/broken", run=status_then_fail), status_server(_vanilla(), [])
    )

    assert isinstance(error, ScenarioError)
    assert isinstance(error.__cause__, ProcessLookupError)
    assert str(error) == "ProcessLookupError: the script broke"
    assert error.transcript.scenario_id == "test/broken"
    names = [event.packet.name for event in error.transcript.events]
    assert names[-1] == "minecraft:status_response"


@pytest.mark.asyncio
async def test_a_scenario_error_closes_the_bots_it_opened() -> None:
    closed: list[bool] = []

    async def wait_for_eof(peer: Peer) -> None:
        await peer.eof()
        closed.append(True)

    async def connect_then_fail(context: ScenarioContext) -> None:
        await context.bot("status")
        raise ProcessLookupError

    async with serve(Codec.for_target(TARGET), wait_for_eof) as endpoint:
        with pytest.raises(ScenarioError):
            await run_scenario(
                Scenario(id="test/x", run=connect_then_fail), endpoint, server="f", timeout_s=1.0
            )

    assert closed == [True]


@pytest.mark.asyncio
async def test_equal_transcripts_are_a_match() -> None:
    reference = await _against(BASIC, _vanilla())
    candidate = await _against(BASIC, _vanilla())

    assert judge(BASIC, reference, candidate) == Verdict("status/basic", Outcome.MATCH)


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
    reference = ScenarioError(Transcript("status/basic", "vanilla"), "TimeoutError: no answer")
    candidate = await _against(BASIC, _vanilla())

    verdict = judge(BASIC, reference, candidate)

    assert verdict.outcome is Outcome.ERROR
    assert verdict.divergences == ()
    assert verdict.detail == "the Reference failed: TimeoutError: no answer"


@pytest.mark.asyncio
async def test_a_harness_failure_on_the_candidate_is_an_error_naming_it() -> None:
    reference = await _against(BASIC, _vanilla())
    candidate = ScenarioError(Transcript("status/basic", "fake"), "ProcessLookupError")
    candidate.__cause__ = ProcessLookupError()  # not something the Candidate did

    verdict = judge(BASIC, reference, candidate)

    assert verdict.outcome is Outcome.ERROR
    assert verdict.divergences == ()
    assert verdict.detail == "the harness failed on the Candidate: ProcessLookupError"


def test_a_comparison_the_harness_cannot_make_is_an_error() -> None:
    odd = Packet(
        state=State.STATUS,
        direction=Direction.CLIENTBOUND,
        name="minecraft:status_response",
        packet_id=0,
        payload=b"",
        fields={"json_response": {1, 2}},  # outside the codec value model: a harness bug
    )
    reference = Transcript("status/basic", "vanilla")
    reference.record("status", odd, t_ns=0)

    verdict = judge(BASIC, reference, Transcript("status/basic", "fake"))

    assert verdict.outcome is Outcome.ERROR
    assert verdict.detail.startswith("the Comparison failed: TypeError: ")


def test_a_scenario_whose_prerequisite_matched_is_not_blocked() -> None:
    assert blocked(PING, {"status/basic": Verdict("status/basic", Outcome.MATCH)}) is None


@pytest.mark.parametrize("outcome", [Outcome.MISMATCH, Outcome.BLOCKED, Outcome.ERROR])
def test_a_scenario_whose_prerequisite_did_not_match_is_blocked(outcome: Outcome) -> None:
    verdict = blocked(PING, {"status/basic": Verdict("status/basic", outcome)})

    assert verdict == Verdict(
        "status/ping", Outcome.BLOCKED, detail=f"prerequisite status/basic was {outcome}"
    )


def test_a_scenario_whose_prerequisite_did_not_run_is_blocked() -> None:
    verdict = blocked(PING, {})

    assert verdict == Verdict(
        "status/ping", Outcome.BLOCKED, detail="prerequisite status/basic was not run"
    )
