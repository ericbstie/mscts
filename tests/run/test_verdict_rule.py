"""The Verdict rule (audit H3): a failure the Candidate caused is a `mismatch`, never `error`.

Each Candidate failure mode is a fake server the Group is played against, as the
Candidate; the Reference side is a well-behaved fake. `error` stays for the harness,
and for the Reference itself failing.
"""

import contextlib
import json
from dataclasses import dataclass

import pytest

from mscts.codec.packets import Codec
from mscts.codec.wire import Writer
from mscts.compare import Divergence, Mask, Outcome, Verdict
from mscts.group import Group, GroupContext
from mscts.groups import status
from mscts.net import Endpoint, ProtocolError
from mscts.run import GroupError, judge, run_group
from mscts.target import TARGET
from mscts.transcript import Transcript
from tests.compare.build import divergence
from tests.net.fakes import VANILLA_STATUS, Handler, Peer, free_port, serve, status_server

BASIC = Group(id="status/basic", run=status.basic)
TIMEOUT_S = 0.2


async def _play(group: Group, handler: Handler | None) -> Transcript | GroupError:
    """Play `group` against a fake running `handler`, or against a closed port if None."""
    if handler is None:
        return await _attempt(group, Endpoint("127.0.0.1", free_port()))
    async with serve(Codec.for_target(TARGET), handler) as endpoint:
        return await _attempt(group, endpoint)


async def _attempt(group: Group, endpoint: Endpoint) -> Transcript | GroupError:
    try:
        return await run_group(group, endpoint, server="fake", timeout_s=TIMEOUT_S)
    except GroupError as error:  # caught inside serve, which would replace its cause
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


def _failed(description: str, bot: str = "status") -> Divergence:
    return divergence("failed", bot=bot, candidate=description)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES.values(), ids=MODES.keys())
async def test_a_candidate_failure_is_a_mismatch_that_says_what_happened(mode: Mode) -> None:
    reference = await _play(BASIC, status_server(_status_json(), []))
    candidate = await _play(BASIC, mode.handler)
    assert isinstance(candidate, GroupError)

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
    assert isinstance(candidate, GroupError)

    verdict = judge(BASIC, reference, candidate)

    assert verdict.test_cases == ("status_response",)  # kept from the Comparison
    [_, payload] = verdict.divergences
    reference_payload = reference.events[-1].packet.payload
    assert payload == divergence(
        "field",
        bot="status",
        packet="minecraft:status_response",
        reference=reference_payload.hex(),
        candidate=(reference_payload + b"\x00").hex(),
        test_case="status_response",
    )


@pytest.mark.asyncio
async def test_a_candidate_failure_survives_a_mask_on_the_whole_packet() -> None:
    mask = Mask(packet="minecraft:status_response", path="*", reason="test only")
    masked = Group(id="status/basic", run=status.basic, masks=(mask,))
    reference = await _play(masked, status_server(_status_json(), []))
    candidate = await _play(masked, _trailing_byte)
    assert isinstance(candidate, GroupError)

    verdict = judge(masked, reference, candidate)

    assert verdict.outcome is Outcome.MISMATCH
    assert verdict.divergences == (_failed(str(candidate)),)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES.values(), ids=MODES.keys())
async def test_the_same_failure_on_the_reference_is_an_error(mode: Mode) -> None:
    reference = await _play(BASIC, mode.handler)
    candidate = await _play(BASIC, status_server(_status_json(), []))
    assert isinstance(reference, GroupError)

    verdict = judge(BASIC, reference, candidate)

    assert verdict == Verdict(
        "status/basic", Outcome.ERROR, detail=f"the Reference failed: {reference}"
    )


async def _two_bots(context: GroupContext) -> None:
    """A Bot that only connects, then one that asks for the status."""
    await context.bot("idle")
    asker = await context.bot("asker")
    await asker.status()


async def _not_a_bot(context: GroupContext) -> None:
    """The script itself raises a Candidate failure, out of no Bot."""
    await context.bot("status")
    msg = "raised by the script"
    raise ProtocolError(msg)


@dataclass(frozen=True)
class Raiser:
    script: Group
    bot: str


RAISERS = {
    "the bot that raised, not the first": Raiser(Group(id="test/two-bots", run=_two_bots), "asker"),
    "no bot: the script raised": Raiser(Group(id="test/not-a-bot", run=_not_a_bot), ""),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("raiser", RAISERS.values(), ids=RAISERS.keys())
async def test_the_failed_divergence_names_the_bot_the_failure_came_out_of(raiser: Raiser) -> None:
    group = raiser.script
    candidate = await _play(group, _mute)
    assert isinstance(candidate, GroupError)

    verdict = judge(group, Transcript(group.id, "vanilla"), candidate)

    assert verdict.outcome is Outcome.MISMATCH
    assert verdict.divergences[0] == _failed(str(candidate), raiser.bot)


async def _mute(peer: Peer) -> None:
    """Take whatever each connection sends, answer nothing, until it closes."""
    with contextlib.suppress(EOFError):
        while True:
            await peer.recv()
