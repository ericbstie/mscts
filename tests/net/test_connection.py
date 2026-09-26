"""Connection transport: framing, recording and timestamps, over a fake localhost server.

These use the handshake-only `toy_codec`, so no State changes are involved.
"""

import asyncio
import socket

import pytest

from mscts.codec.packets import Codec, CodecError, Direction, Packet, State
from mscts.net import Connection, ConnectionClosedError
from mscts.transcript import Event, Transcript
from tests.net.fakes import Peer, connected, serve


def test_open_connects_and_close_ends_the_connection(
    toy_codec: Codec, transcript: Transcript
) -> None:
    async def server(peer: Peer) -> None:
        await peer.eof()

    async def client() -> None:
        async with serve(toy_codec, server) as endpoint:
            connection = await Connection.open(
                endpoint, toy_codec, bot="alice", transcript=transcript
            )
            await connection.close()

    asyncio.run(client())
    assert transcript.events == []


def test_open_turns_off_nagle_so_small_writes_are_not_delayed(
    toy_codec: Codec, transcript: Transcript, monkeypatch: pytest.MonkeyPatch
) -> None:
    writers: list[asyncio.StreamWriter] = []
    open_connection = asyncio.open_connection

    async def recording_open_connection(
        host: str, port: int
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        reader, writer = await open_connection(host, port)
        writers.append(writer)
        return reader, writer

    monkeypatch.setattr(asyncio, "open_connection", recording_open_connection)

    async def server(peer: Peer) -> None:
        await peer.eof()

    async def client() -> None:
        async with serve(toy_codec, server) as endpoint, connected(endpoint, toy_codec, transcript):
            sock = writers[0].get_extra_info("socket")
            assert sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY)

    asyncio.run(client())


def test_send_writes_one_frame_the_server_decodes(toy_codec: Codec, transcript: Transcript) -> None:
    received: list[Packet] = []

    async def server(peer: Peer) -> None:
        received.append(await peer.recv())
        await peer.eof()

    async def client() -> None:
        async with (
            serve(toy_codec, server) as endpoint,
            connected(endpoint, toy_codec, transcript) as connection,
        ):
            await connection.send("test:request", value=-7)

    asyncio.run(client())
    assert [(packet.name, packet.fields) for packet in received] == [
        ("test:request", {"value": -7})
    ]


def test_send_records_the_packet_as_it_went_on_the_wire(
    toy_codec: Codec, transcript: Transcript
) -> None:
    async def server(peer: Peer) -> None:
        await peer.recv()
        await peer.eof()

    async def client() -> None:
        async with (
            serve(toy_codec, server) as endpoint,
            connected(endpoint, toy_codec, transcript) as connection,
        ):
            await connection.send("test:request", value=-7)

    asyncio.run(client())
    [event] = transcript.events
    assert event == Event(
        t_ns=event.t_ns,
        bot="alice",
        packet=Packet(
            state=State.HANDSHAKE,
            direction=Direction.SERVERBOUND,
            name="test:request",
            packet_id=0x00,
            payload=(-7).to_bytes(8, "big", signed=True),
            fields={"value": -7},
        ),
    )


def test_send_accepts_a_field_called_name(toy_codec: Codec, transcript: Transcript) -> None:
    received: list[Packet] = []

    async def server(peer: Peer) -> None:
        received.append(await peer.recv())
        await peer.eof()

    async def client() -> None:
        async with (
            serve(toy_codec, server) as endpoint,
            connected(endpoint, toy_codec, transcript) as connection,
        ):
            await connection.send("test:hello", name="Steve")

    asyncio.run(client())
    assert [packet.fields for packet in received] == [{"name": "Steve"}]


def test_send_stamps_the_event_immediately_before_the_write(
    toy_codec: Codec, transcript: Transcript, monkeypatch: pytest.MonkeyPatch
) -> None:
    writes: list[int] = []
    write = asyncio.StreamWriter.write

    def recording_write(self: asyncio.StreamWriter, data: bytes) -> None:
        writes.append(transcript.now_ns())
        write(self, data)

    async def server(peer: Peer) -> None:
        await peer.recv()
        await peer.eof()

    async def client() -> int:
        async with (
            serve(toy_codec, server) as endpoint,
            connected(endpoint, toy_codec, transcript) as connection,
        ):
            monkeypatch.setattr(asyncio.StreamWriter, "write", recording_write)
            before = transcript.now_ns()
            await connection.send("test:request", value=1)
            monkeypatch.undo()
            return before

    before = asyncio.run(client())
    [event] = transcript.events
    [written] = writes
    assert before <= event.t_ns <= written


def test_send_of_fields_that_do_not_fit_raises_and_neither_writes_nor_records(
    toy_codec: Codec, transcript: Transcript
) -> None:
    received: list[Packet] = []

    async def server(peer: Peer) -> None:
        received.append(await peer.recv())
        await peer.eof()

    async def client() -> None:
        async with (
            serve(toy_codec, server) as endpoint,
            connected(endpoint, toy_codec, transcript) as connection,
        ):
            with pytest.raises(CodecError, match="value: expected an int"):
                await connection.send("test:request", value="seven")
            await connection.send("test:request", value=7)

    asyncio.run(client())
    assert [packet.fields for packet in received] == [{"value": 7}]
    assert [event.packet.fields for event in transcript.events] == [{"value": 7}]


def test_close_is_idempotent(toy_codec: Codec, transcript: Transcript) -> None:
    async def server(peer: Peer) -> None:
        await peer.eof()

    async def client() -> None:
        async with (
            serve(toy_codec, server) as endpoint,
            connected(endpoint, toy_codec, transcript) as connection,
        ):
            await connection.close()
            await connection.close()

    asyncio.run(client())


def test_send_after_close_raises(toy_codec: Codec, transcript: Transcript) -> None:
    async def server(peer: Peer) -> None:
        await peer.eof()

    async def client() -> None:
        async with (
            serve(toy_codec, server) as endpoint,
            connected(endpoint, toy_codec, transcript) as connection,
        ):
            await connection.close()
            with pytest.raises(ConnectionClosedError, match="closed"):
                await connection.send("test:request", value=7)

    asyncio.run(client())
    assert transcript.events == []
