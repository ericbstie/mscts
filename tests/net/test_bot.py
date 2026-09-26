"""Bot status and ping, against a fake localhost server using the Target's Codec."""

import asyncio
import json

import pytest

from mscts.bot import Bot
from mscts.codec.packets import Codec, Direction, Packet
from mscts.net import Connection, Endpoint, ProtocolError
from mscts.target import TARGET
from mscts.transcript import Transcript
from tests.net.fakes import VANILLA_STATUS, Peer, status_server, with_bot


async def status(bot: Bot) -> object:
    return await bot.status()


def test_status_returns_the_parsed_status_json(codec: Codec, transcript: Transcript) -> None:
    handler = status_server(json.dumps(VANILLA_STATUS), [])
    result, _ = with_bot(codec, transcript, handler, status)
    assert result == VANILLA_STATUS


def test_status_handshakes_with_the_target_protocol_and_the_endpoint(
    codec: Codec, transcript: Transcript
) -> None:
    seen: list[Packet] = []
    _, endpoint = with_bot(
        codec, transcript, status_server(json.dumps(VANILLA_STATUS), seen), status
    )
    assert [(packet.name, packet.fields) for packet in seen] == [
        (
            "minecraft:intention",
            {
                "protocol_version": 777,
                "server_address": endpoint.host,
                "server_port": endpoint.port,
                "intent": 1,
            },
        ),
        ("minecraft:status_request", {}),
    ]


def test_status_records_the_exchange_as_the_bot(codec: Codec, transcript: Transcript) -> None:
    with_bot(codec, transcript, status_server(json.dumps(VANILLA_STATUS), []), status)
    assert [
        (event.bot, event.packet.direction, event.packet.name) for event in transcript.events
    ] == [
        ("alice", Direction.SERVERBOUND, "minecraft:intention"),
        ("alice", Direction.SERVERBOUND, "minecraft:status_request"),
        ("alice", Direction.CLIENTBOUND, "minecraft:status_response"),
    ]


def test_a_bot_has_its_name(codec: Codec, transcript: Transcript) -> None:
    async def name(bot: Bot) -> str:
        return bot.name

    async def server(peer: Peer) -> None:
        await peer.eof()

    assert with_bot(codec, transcript, server, name)[0] == "alice"


def test_ping_after_status_gets_its_payload_echoed(codec: Codec, transcript: Transcript) -> None:
    async def status_then_ping(bot: Bot) -> None:
        await bot.status()
        await bot.ping(-123_456_789_012)

    with_bot(codec, transcript, status_server(json.dumps(VANILLA_STATUS), []), status_then_ping)
    assert [(event.packet.name, event.packet.fields) for event in transcript.events[-2:]] == [
        ("minecraft:ping_request", {"timestamp": -123_456_789_012}),
        ("minecraft:pong_response", {"timestamp": -123_456_789_012}),
    ]


def test_ping_without_status_handshakes_first(codec: Codec, transcript: Transcript) -> None:
    seen: list[Packet] = []

    async def ping(bot: Bot) -> None:
        await bot.ping(7)

    with_bot(codec, transcript, status_server(json.dumps(VANILLA_STATUS), seen), ping)
    assert [packet.name for packet in seen] == ["minecraft:intention", "minecraft:ping_request"]


def test_ping_raises_when_the_pong_echoes_another_payload(
    codec: Codec, transcript: Transcript
) -> None:
    async def server(peer: Peer) -> None:
        await peer.recv()
        await peer.recv()
        await peer.send("minecraft:pong_response", timestamp=8)
        await peer.eof()

    async def ping(bot: Bot) -> None:
        with pytest.raises(ProtocolError, match="pong_response echoed 8, not the ping payload 7"):
            await bot.ping(7)

    with_bot(codec, transcript, server, ping)
    assert transcript.events[-1].packet.fields == {"timestamp": 8}


def test_status_raises_on_another_answer_and_still_records_it(
    codec: Codec, transcript: Transcript
) -> None:
    async def server(peer: Peer) -> None:
        await peer.recv()
        await peer.recv()
        await peer.send("minecraft:pong_response", timestamp=1)
        await peer.eof()

    async def raises(bot: Bot) -> None:
        with pytest.raises(
            ProtocolError,
            match="expected minecraft:status_response, got minecraft:pong_response",
        ):
            await bot.status()

    with_bot(codec, transcript, server, raises)
    assert transcript.events[-1].packet.name == "minecraft:pong_response"


@pytest.mark.parametrize(
    ("json_response", "problem"),
    [
        ("not json", "is not JSON"),
        ("[]", "is not a JSON object"),
        ('"mscts"', "is not a JSON object"),
    ],
)
def test_status_raises_unless_the_answer_is_a_json_object(
    codec: Codec, transcript: Transcript, json_response: str, problem: str
) -> None:
    async def raises(bot: Bot) -> None:
        with pytest.raises(ProtocolError, match=f"status_response json_response {problem}"):
            await bot.status()

    with_bot(codec, transcript, status_server(json_response, []), raises)


def test_status_times_out_when_the_server_does_not_answer(
    codec: Codec, transcript: Transcript
) -> None:
    async def server(peer: Peer) -> None:
        await peer.recv()
        await peer.recv()
        await peer.eof()

    async def raises(bot: Bot) -> float:
        loop = asyncio.get_running_loop()
        start = loop.time()
        with pytest.raises(TimeoutError):
            await bot.status()
        return loop.time() - start

    elapsed, _ = with_bot(codec, transcript, server, raises, timeout_s=0.05)
    assert 0.05 <= elapsed < 0.5


async def hang(*args: object, **kwargs: object) -> None:
    del args, kwargs
    await asyncio.Event().wait()


@pytest.mark.parametrize("operation", ["status", "ping"])
def test_status_and_ping_are_bounded_even_when_a_send_blocks(
    codec: Codec, transcript: Transcript, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    # A server that stops reading eventually blocks the client's writes.
    monkeypatch.setattr(Connection, "send", hang)

    async def server(peer: Peer) -> None:
        await peer.eof()

    async def raises(bot: Bot) -> float:
        loop = asyncio.get_running_loop()
        start = loop.time()
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(1):  # a guard: without Bot's own bound, this fires
                await (bot.status() if operation == "status" else bot.ping(1))
        return loop.time() - start

    elapsed, _ = with_bot(codec, transcript, server, raises, timeout_s=0.05)
    assert 0.05 <= elapsed < 0.5


def test_connect_is_bounded(transcript: Transcript, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Connection, "open", hang)

    async def client() -> float:
        loop = asyncio.get_running_loop()
        start = loop.time()
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(1):  # a guard: without Bot's own bound, this fires
                await Bot.connect(
                    Endpoint(host="127.0.0.1", port=1),
                    TARGET,
                    name="alice",
                    transcript=transcript,
                    timeout_s=0.05,
                )
        return loop.time() - start

    assert 0.05 <= asyncio.run(client()) < 0.5
