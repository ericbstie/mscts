import json

import pytest

from mscts.codec.packets import Codec, Packet
from mscts.net import ConnectionClosedError, Endpoint
from mscts.scenario import ScenarioContext
from mscts.target import TARGET
from mscts.transcript import Mark, Transcript
from tests.net.fakes import VANILLA_STATUS, serve, status_server

_UNUSED = Endpoint(host="127.0.0.1", port=1)


@pytest.mark.asyncio
async def test_a_span_marks_its_start_and_end() -> None:
    transcript = Transcript(scenario_id="test/span", server="fake")
    context = ScenarioContext(_UNUSED, transcript, timeout_s=1.0)

    async with context.span("status.rtt"):
        inside = list(transcript.marks)

    assert [mark.label for mark in inside] == ["status.rtt:start"]
    assert [mark.label for mark in transcript.marks] == ["status.rtt:start", "status.rtt:end"]
    start, end = transcript.marks
    assert 0 <= start.t_ns <= end.t_ns <= transcript.now_ns()


@pytest.mark.asyncio
async def test_a_span_whose_body_raises_has_no_end_mark() -> None:
    transcript = Transcript(scenario_id="test/span", server="fake")
    context = ScenarioContext(_UNUSED, transcript, timeout_s=1.0)

    async def fail_inside() -> None:
        async with context.span("broken"):
            raise ProcessLookupError

    with pytest.raises(ProcessLookupError):
        await fail_inside()

    assert [mark.label for mark in transcript.marks] == ["broken:start"]


@pytest.mark.asyncio
async def test_control_is_not_built_yet_and_says_when_it_will_be() -> None:
    context = ScenarioContext(_UNUSED, Transcript(scenario_id="t", server="f"), timeout_s=1.0)

    with pytest.raises(NotImplementedError, match="M5"):
        _ = context.control


@pytest.mark.asyncio
async def test_a_bot_records_to_the_context_transcript_and_close_closes_it() -> None:
    codec = Codec.for_target(TARGET)
    transcript = Transcript(scenario_id="test/bot", server="fake")
    seen: list[Packet] = []

    async with serve(codec, status_server(json.dumps(VANILLA_STATUS), seen)) as endpoint:
        context = ScenarioContext(endpoint, transcript, timeout_s=1.0)
        try:
            bot = await context.bot("alice")
            assert await bot.status() == VANILLA_STATUS
        finally:
            await context.close()
        with pytest.raises(ConnectionClosedError):
            await bot.status()

    assert context.endpoint == endpoint
    assert {event.bot for event in transcript.events} == {"alice"}
    assert [event.packet.name for event in transcript.events] == [
        "minecraft:intention",
        "minecraft:status_request",
        "minecraft:status_response",
    ]
    assert transcript.marks == list[Mark]()


@pytest.mark.asyncio
async def test_two_bots_of_one_name_are_refused() -> None:
    codec = Codec.for_target(TARGET)
    transcript = Transcript(scenario_id="test/bot", server="fake")

    async with serve(codec, status_server("{}", [])) as endpoint:
        context = ScenarioContext(endpoint, transcript, timeout_s=1.0)
        try:
            await context.bot("alice")
            with pytest.raises(ValueError, match="alice"):
                await context.bot("alice")
        finally:
            await context.close()
