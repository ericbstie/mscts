"""Bot.join and Bot.expect, against a fake server that joins like vanilla 26.3."""

import asyncio
import json
import uuid

import pytest

from mscts.bot import CHUNKS_PER_TICK, Bot, offline_uuid
from mscts.codec.packets import Codec, Direction, Packet, State
from mscts.net import ProtocolError
from mscts.transcript import Transcript
from tests.net.fakes import (
    SPAWN,
    VANILLA_STATUS,
    JoinScript,
    Peer,
    join_server,
    status_server,
    with_bot,
)

JOIN_SENDS = [
    "minecraft:intention",
    "minecraft:hello",
    "minecraft:login_acknowledged",
    "minecraft:select_known_packs",
    "minecraft:finish_configuration",
    "minecraft:accept_teleportation",
    "minecraft:chunk_batch_received",
]
"""What the vanilla client sends on its way to play's first chunk batch (26.3 javap)."""


async def join(bot: Bot) -> None:
    await bot.join()


def taken(transcript: Transcript) -> list[tuple[State, str]]:
    return [
        (event.packet.state, event.packet.name)
        for event in transcript.events
        if event.packet.direction is Direction.CLIENTBOUND
    ]


def test_offline_uuid_is_the_one_vanilla_gives_the_name() -> None:
    # UUIDUtil.createOfflinePlayerUUID (26.3 javap): Java's UUID.nameUUIDFromBytes of
    # "OfflinePlayer:" + name in UTF-8. The values are what Java 25 computes for it.
    assert offline_uuid("Notch") == uuid.UUID("b50ad385-829d-3141-a216-7e7d7539ba7f")
    assert offline_uuid("alice") == uuid.UUID("40f5db53-a47a-33ee-b1f6-db0e20deded4")


def test_join_sends_what_the_vanilla_client_sends(codec: Codec, transcript: Transcript) -> None:
    seen: list[Packet] = []
    _, endpoint = with_bot(codec, transcript, join_server(seen), join)
    assert [packet.name for packet in seen] == JOIN_SENDS
    intention, hello, *_, teleport, chunk_batch = seen
    assert intention.fields == {
        "protocol_version": 777,
        "server_address": endpoint.host,
        "server_port": endpoint.port,
        "intent": 2,
    }
    assert hello.fields == {"name": "alice", "player_uuid": offline_uuid("alice")}
    assert teleport.fields == {"teleport_id": 1, **SPAWN}
    assert chunk_batch.fields == {"chunks_per_tick": CHUNKS_PER_TICK}


def test_join_returns_once_the_first_chunk_batch_has_finished(
    codec: Codec, transcript: Transcript
) -> None:
    with_bot(codec, transcript, join_server([]), join)
    assert taken(transcript)[-1] == (State.PLAY, "minecraft:chunk_batch_finished")
    assert [event.packet.name for event in transcript.events if event.bot == "alice"][-2:] == [
        "minecraft:chunk_batch_finished",
        "minecraft:chunk_batch_received",
    ]


@pytest.mark.parametrize("threshold", [None, 0, 256, -1])
def test_join_works_whatever_compression_the_server_chooses(
    codec: Codec, transcript: Transcript, threshold: int | None
) -> None:
    seen: list[Packet] = []
    script = JoinScript(compression_threshold=threshold)
    with_bot(codec, transcript, join_server(seen, script), join)
    assert [packet.name for packet in seen] == JOIN_SENDS


def test_join_accepts_a_code_of_conduct(codec: Codec, transcript: Transcript) -> None:
    seen: list[Packet] = []
    script = JoinScript(code_of_conduct="Be kind.")
    with_bot(codec, transcript, join_server(seen, script), join)
    assert [packet.name for packet in seen][3:6] == [
        "minecraft:select_known_packs",
        "minecraft:accept_code_of_conduct",
        "minecraft:finish_configuration",
    ]


def test_the_bot_answers_a_keep_alive_while_no_one_reads(
    codec: Codec, transcript: Transcript
) -> None:
    seen: list[Packet] = []
    echoed = asyncio.Event()

    async def after_the_echo(peer: Peer) -> None:
        del peer
        echoed.set()

    async def join_then_idle(bot: Bot) -> None:
        await bot.join()
        async with asyncio.timeout(1):
            await echoed.wait()

    script = JoinScript(keep_alive_id=-42, then=after_the_echo)
    with_bot(codec, transcript, join_server(seen, script), join_then_idle)
    assert (seen[-1].name, seen[-1].fields) == ("minecraft:keep_alive", {"keep_alive_id": -42})
    assert taken(transcript)[-1] == (State.PLAY, "minecraft:chunk_batch_finished")


@pytest.mark.parametrize("state", [State.LOGIN, State.CONFIGURATION, State.PLAY])
def test_join_raises_when_the_server_disconnects_the_bot(
    codec: Codec, transcript: Transcript, state: State
) -> None:
    async def raises(bot: Bot) -> None:
        with pytest.raises(ProtocolError, match=f"the server disconnected alice in {state}: "):
            await bot.join()

    with_bot(codec, transcript, join_server([], JoinScript(disconnect_in=state)), raises)
    assert taken(transcript)[-1][1].endswith("disconnect")


def test_join_raises_when_the_server_asks_for_encryption(
    codec: Codec, transcript: Transcript
) -> None:
    async def online_mode(peer: Peer) -> None:
        await peer.recv()
        await peer.recv()
        await peer.write(peer.raw_frame("minecraft:hello", bytes.fromhex("00 01 00 01 00 01")))
        await peer.eof()

    async def raises(bot: Bot) -> None:
        with pytest.raises(ProtocolError, match="asks for encryption"):
            await bot.join()

    with_bot(codec, transcript, online_mode, raises)


def test_join_is_bounded(codec: Codec, transcript: Transcript) -> None:
    async def silent(peer: Peer) -> None:
        await peer.recv()
        await peer.recv()
        await peer.eof()

    async def raises(bot: Bot) -> float:
        loop = asyncio.get_running_loop()
        start = loop.time()
        with pytest.raises(TimeoutError):
            await bot.join()
        return loop.time() - start

    elapsed, _ = with_bot(codec, transcript, silent, raises, timeout_s=0.05)
    assert 0.05 <= elapsed < 0.5


def test_join_needs_a_fresh_connection(codec: Codec, transcript: Transcript) -> None:
    seen: list[Packet] = []

    async def status_then_join(bot: Bot) -> None:
        await bot.status()
        with pytest.raises(ProtocolError, match="join needs a fresh Connection, not one in status"):
            await bot.join()

    with_bot(codec, transcript, status_server(json.dumps(VANILLA_STATUS), seen), status_then_join)
    assert [packet.name for packet in seen] == ["minecraft:intention", "minecraft:status_request"]


def play(*frames: tuple[str, bytes]) -> JoinScript:
    """Join, then send each (name, payload) as a raw play frame."""

    async def send(peer: Peer) -> None:
        for name, payload in frames:
            await peer.write(peer.raw_frame(name, payload))

    return JoinScript(then=send)


DIFFICULTY = "minecraft:change_difficulty"  # no schema, and the Bot does not answer it


def test_expect_takes_packets_until_one_has_the_name(codec: Codec, transcript: Transcript) -> None:
    async def expect(bot: Bot) -> Packet:
        await bot.join()
        return await bot.expect("minecraft:chunk_batch_start", timeout_s=1)

    script = play(
        (DIFFICULTY, b"\x01\x00"), ("minecraft:chunk_batch_start", b""), (DIFFICULTY, b"")
    )
    packet, _ = with_bot(codec, transcript, join_server([], script), expect)
    assert (packet.state, packet.name) == (State.PLAY, "minecraft:chunk_batch_start")
    assert taken(transcript)[-3:] == [
        (State.PLAY, "minecraft:chunk_batch_finished"),
        (State.PLAY, DIFFICULTY),
        (State.PLAY, "minecraft:chunk_batch_start"),
    ]


def test_expect_takes_packets_until_where_holds(codec: Codec, transcript: Transcript) -> None:
    async def expect(bot: Bot) -> Packet:
        await bot.join()
        return await bot.expect(DIFFICULTY, timeout_s=1, where=lambda p: p.payload == b"\x02\x00")

    script = play((DIFFICULTY, b"\x01\x00"), (DIFFICULTY, b"\x02\x00"), (DIFFICULTY, b"\x03\x00"))
    packet, _ = with_bot(codec, transcript, join_server([], script), expect)
    assert packet.payload == b"\x02\x00"
    assert taken(transcript)[-2:] == [(State.PLAY, DIFFICULTY)] * 2


def test_expect_is_bounded(codec: Codec, transcript: Transcript) -> None:
    async def raises(bot: Bot) -> float:
        await bot.join()
        loop = asyncio.get_running_loop()
        start = loop.time()
        with pytest.raises(TimeoutError):
            await bot.expect("minecraft:keep_alive", timeout_s=0.05)
        return loop.time() - start

    elapsed, _ = with_bot(codec, transcript, join_server([]), raises)
    assert 0.05 <= elapsed < 0.5


def test_expect_raises_when_the_server_disconnects_the_bot_first(
    codec: Codec, transcript: Transcript
) -> None:
    async def raises(bot: Bot) -> None:
        await bot.join()
        with pytest.raises(ProtocolError, match="the server disconnected alice in play: "):
            await bot.expect("minecraft:keep_alive", timeout_s=1)

    script = play(("minecraft:disconnect", bytes.fromhex("08 0004") + b"kick"))
    with_bot(codec, transcript, join_server([], script), raises)


def test_expect_returns_a_disconnect_it_expects(codec: Codec, transcript: Transcript) -> None:
    async def expect(bot: Bot) -> Packet:
        await bot.join()
        return await bot.expect("minecraft:disconnect", timeout_s=1)

    script = play(("minecraft:disconnect", bytes.fromhex("08 0004") + b"kick"))
    packet, _ = with_bot(codec, transcript, join_server([], script), expect)
    assert packet.fields == {"reason": bytes.fromhex("08 0004") + b"kick"}
