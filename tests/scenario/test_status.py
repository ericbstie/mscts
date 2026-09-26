import json

import pytest

from mscts.codec.packets import Codec, Packet
from mscts.scenario import SCENARIOS, Scenario, ScenarioContext, ScenarioKind, resolve
from mscts.scenarios import status
from mscts.target import TARGET
from mscts.transcript import Transcript
from tests.net.fakes import VANILLA_STATUS, serve, status_server


async def _play(scenario: Scenario) -> tuple[Transcript, list[Packet]]:
    codec = Codec.for_target(TARGET)
    transcript = Transcript(scenario_id=scenario.id, server="fake")
    seen: list[Packet] = []
    async with serve(codec, status_server(json.dumps(VANILLA_STATUS), seen)) as endpoint:
        context = ScenarioContext(endpoint, transcript, timeout_s=1.0)
        try:
            await scenario.run(context)
        finally:
            await context.close()
    return transcript, seen


def _names(transcript: Transcript) -> list[str]:
    return [event.packet.name for event in transcript.events]


def test_both_status_scenarios_are_registered_as_exact_with_no_masks() -> None:
    basic, ping = SCENARIOS["status/basic"], SCENARIOS["status/ping"]

    assert (basic.run, ping.run) == (status.basic, status.ping)
    assert basic.kind is ping.kind is ScenarioKind.EXACT
    assert basic.masks == ping.masks == ()


def test_status_ping_needs_status_basic_to_match_first() -> None:
    assert SCENARIOS["status/ping"].requires == ("status/basic",)
    assert SCENARIOS["status/basic"].requires == ()
    assert [each.id for each in resolve(["status/ping"])] == ["status/basic", "status/ping"]


@pytest.mark.asyncio
async def test_status_basic_asks_for_the_status_once() -> None:
    transcript, seen = await _play(SCENARIOS["status/basic"])

    assert _names(transcript) == [
        "minecraft:intention",
        "minecraft:status_request",
        "minecraft:status_response",
    ]
    assert [packet.name for packet in seen] == _names(transcript)[:2]
    assert transcript.marks == []


@pytest.mark.asyncio
async def test_status_ping_pings_after_the_status_as_the_vanilla_client_does() -> None:
    transcript, _ = await _play(SCENARIOS["status/ping"])

    assert _names(transcript) == [
        "minecraft:intention",
        "minecraft:status_request",
        "minecraft:status_response",
        "minecraft:ping_request",
        "minecraft:pong_response",
    ]
    pong = transcript.events[-1].packet
    assert pong.fields == {"timestamp": status.PING_PAYLOAD}


@pytest.mark.asyncio
async def test_the_status_rtt_span_covers_exactly_the_ping_and_its_pong() -> None:
    transcript, _ = await _play(SCENARIOS["status/ping"])

    start, end = transcript.marks
    ping, pong = transcript.events[-2:]
    assert (start.label, end.label) == ("status.rtt:start", "status.rtt:end")
    assert transcript.events[-3].t_ns <= start.t_ns <= ping.t_ns
    assert pong.t_ns <= end.t_ns
