"""Bot.status and Bot.ping against a live vanilla 26.3, sharing one session-scoped Reference.

Pins the handshake/status wire layouts (ADR-0003) against the real Reference, not just
wiki samples or a fake server: the exact status JSON vanilla answers for the default
ServerSpec, the ping echo, and that every packet the Codec has a schema for decodes
with fields (never `fields=None`) from the real bytes on the wire.
"""

import pytest

from mscts.bot import Bot
from mscts.runner import Instance
from mscts.target import TARGET
from mscts.transcript import Transcript
from tests.net.fakes import VANILLA_STATUS

pytestmark = [pytest.mark.reference, pytest.mark.asyncio(loop_scope="session")]

_TIMEOUT_S = 5.0


async def _connect(reference: Instance, transcript: Transcript, *, name: str) -> Bot:
    return await Bot.connect(
        reference.endpoint, TARGET, name=name, transcript=transcript, timeout_s=_TIMEOUT_S
    )


async def test_status_returns_protocol_777_and_the_exact_status_json(
    reference: Instance,
) -> None:
    transcript = Transcript(scenario_id="reference/status", server="vanilla")
    bot = await _connect(reference, transcript, name="alice")
    try:
        status = await bot.status()
    finally:
        await bot.close()
    # VANILLA_STATUS is exactly what docs/research/2026-09-25-domain.md records vanilla
    # 26.3 answering for the default ServerSpec (motd "mscts"); it includes protocol 777.
    assert status == VANILLA_STATUS


async def test_ping_echoes_its_payload(reference: Instance) -> None:
    transcript = Transcript(scenario_id="reference/ping", server="vanilla")
    bot = await _connect(reference, transcript, name="alice")
    payload = -123_456_789_012
    try:
        await bot.ping(payload)  # raises ProtocolError itself if the echo does not match
    finally:
        await bot.close()
    pong = transcript.events[-1].packet
    assert pong.name == "minecraft:pong_response"
    assert pong.fields == {"timestamp": payload}


async def test_every_recorded_packet_decodes_strictly_with_fields(reference: Instance) -> None:
    transcript = Transcript(scenario_id="reference/strict-decode", server="vanilla")
    bot = await _connect(reference, transcript, name="alice")
    try:
        await bot.status()
        await bot.ping(1)
    finally:
        await bot.close()
    # One handshake (reused for both), then status, then ping: the full sequence
    # ADR-0003 describes, every one of them decoded with a schema.
    assert [event.packet.name for event in transcript.events] == [
        "minecraft:intention",
        "minecraft:status_request",
        "minecraft:status_response",
        "minecraft:ping_request",
        "minecraft:pong_response",
    ]
    assert all(event.packet.fields is not None for event in transcript.events)
