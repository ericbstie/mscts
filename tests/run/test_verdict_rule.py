"""The Verdict rule (audit H3): a failure the Candidate caused is a `mismatch`, never `error`.

Each Candidate failure mode is a fake server the Scenario is played against, as the
Candidate; the Reference side is a well-behaved fake. `error` stays for the harness,
and for the Reference itself failing.
"""

import json
from dataclasses import dataclass

import pytest

from mscts.codec.packets import Codec
from mscts.codec.wire import Writer
from mscts.compare import ABSENT, Divergence, Mask, Outcome, Verdict
from mscts.net import Endpoint
from mscts.run import ScenarioError, judge, run_scenario
from mscts.scenario import Scenario
from mscts.scenarios import status
from mscts.target import TARGET
from mscts.transcript import Transcript
from tests.net.fakes import VANILLA_STATUS, Handler, Peer, free_port, serve, status_server

BASIC = Scenario(id="status/basic", run=status.basic)
TIMEOUT_S = 0.2


async def _play(scenario: Scenario, handler: Handler | None) -> Transcript | ScenarioError:
    """Play `scenario` against a fake running `handler`, or against a closed port if None."""
    if handler is None:
        return await _attempt(scenario, Endpoint("127.0.0.1", free_port()))
    async with serve(Codec.for_target(TARGET), handler) as endpoint:
        return await _attempt(scenario, endpoint)


async def _attempt(scenario: Scenario, endpoint: Endpoint) -> Transcript | ScenarioError:
    try:
        return await run_scenario(scenario, endpoint, server="fake", timeout_s=TIMEOUT_S)
    except ScenarioError as error:  # caught inside serve, which would replace its cause
        return error


def _status_json() -> str:
    return json.dumps(VANILLA_STATUS)


async def _trailing_byte(peer: Peer) -> None:
    await peer.recv()  # the intention
    await peer.recv()  # status_request
    text = Writer().string(_status_json(), max_length=32767).to_bytes()
    await peer.write(peer.raw_frame("minecraft:status_response", text + b"\x00"))
    await peer.eof()


async def _not_an_object(peer: Peer) -> None:
    await peer.recv()
    await peer.recv()
    await peer.send("minecraft:status_response", json_response="[]")
    await peer.eof()


async def _silent(peer: Peer) -> None:
    await peer.recv()
    await peer.recv()
    await peer.eof()


async def _closes(peer: Peer) -> None:
    await peer.recv()
    await peer.recv()


@dataclass(frozen=True)
class Mode:
    handler: Handler | None
    failure: str


MODES = {
    "undecodable frame": Mode(
        _trailing_byte,
        "CodecError: status clientbound minecraft:status_response: 1 unconsumed byte(s) remain",
    ),
    "protocol error": Mode(
        _not_an_object, "ProtocolError: status_response json_response is not a JSON object"
    ),
    "timeout": Mode(_silent, f"TimeoutError: no answer within {TIMEOUT_S} s"),
    "connection closed": Mode(_closes, "ConnectionClosedError: the server closed the connection"),
    "connection refused": Mode(None, "ConnectionRefusedError: "),
}


def _failed(description: str) -> Divergence:
    return Divergence(
        bot="",
        index=0,
        kind="failed",
        packet="",
        path=None,
        reference=ABSENT,
        candidate=description,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES.values(), ids=MODES.keys())
async def test_a_candidate_failure_is_a_mismatch_that_says_what_happened(mode: Mode) -> None:
    reference = await _play(BASIC, status_server(_status_json(), []))
    candidate = await _play(BASIC, mode.handler)
    assert isinstance(candidate, ScenarioError)

    verdict = judge(BASIC, reference, candidate)

    assert verdict.outcome is Outcome.MISMATCH
    failed = verdict.divergences[0]
    assert failed == _failed(str(candidate))
    assert str(candidate).startswith(mode.failure)
    assert verdict.detail == f"the Candidate failed: {candidate}"


@pytest.mark.asyncio
async def test_the_undecodable_frame_is_a_divergence_showing_both_payloads() -> None:
    reference = await _play(BASIC, status_server(_status_json(), []))
    candidate = await _play(BASIC, _trailing_byte)
    assert isinstance(reference, Transcript)
    assert isinstance(candidate, ScenarioError)

    verdict = judge(BASIC, reference, candidate)

    [_, payload] = verdict.divergences
    reference_payload = reference.events[-1].packet.payload
    assert payload == Divergence(
        bot="status",
        index=0,
        kind="field",
        packet="minecraft:status_response",
        path=None,
        reference=reference_payload.hex(),
        candidate=(reference_payload + b"\x00").hex(),
    )


@pytest.mark.asyncio
async def test_a_candidate_failure_survives_a_mask_on_the_whole_packet() -> None:
    mask = Mask(packet="minecraft:status_response", path="*", reason="test only")
    masked = Scenario(id="status/basic", run=status.basic, masks=(mask,))
    reference = await _play(masked, status_server(_status_json(), []))
    candidate = await _play(masked, _trailing_byte)
    assert isinstance(candidate, ScenarioError)

    verdict = judge(masked, reference, candidate)

    assert verdict.outcome is Outcome.MISMATCH
    assert verdict.divergences == (_failed(str(candidate)),)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES.values(), ids=MODES.keys())
async def test_the_same_failure_on_the_reference_is_an_error(mode: Mode) -> None:
    reference = await _play(BASIC, mode.handler)
    candidate = await _play(BASIC, status_server(_status_json(), []))
    assert isinstance(reference, ScenarioError)

    verdict = judge(BASIC, reference, candidate)

    assert verdict == Verdict(
        "status/basic", Outcome.ERROR, detail=f"the Reference failed: {reference}"
    )
