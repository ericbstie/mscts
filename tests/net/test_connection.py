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


def test_recv_returns_and_records_a_clientbound_packet(
    toy_codec: Codec, transcript: Transcript
) -> None:
    async def server(peer: Peer) -> None:
        await peer.send("test:reply", value=42)
        await peer.eof()

    async def client() -> Packet:
        async with (
            serve(toy_codec, server) as endpoint,
            connected(endpoint, toy_codec, transcript) as connection,
        ):
            return await connection.recv(timeout_s=1)

    packet = asyncio.run(client())
    assert packet == Packet(
        state=State.HANDSHAKE,
        direction=Direction.CLIENTBOUND,
        name="test:reply",
        packet_id=0x00,
        payload=(42).to_bytes(8, "big"),
        fields={"value": 42},
    )
    assert transcript.events == [Event(t_ns=transcript.events[0].t_ns, bot="alice", packet=packet)]


def test_recv_reassembles_a_frame_that_arrives_one_byte_at_a_time(
    toy_codec: Codec, transcript: Transcript
) -> None:
    last_byte_written: list[int] = []

    async def server(peer: Peer) -> None:
        frame = peer.frame("test:reply", value=-1)
        for index in range(len(frame)):
            await asyncio.sleep(0.001)  # the client reads each byte on its own
            last_byte_written.append(await peer.write(frame[index : index + 1]))
        await peer.eof()

    async def client() -> Packet:
        async with (
            serve(toy_codec, server) as endpoint,
            connected(endpoint, toy_codec, transcript) as connection,
        ):
            return await connection.recv(timeout_s=1)

    packet = asyncio.run(client())
    assert packet.fields == {"value": -1}
    assert transcript.events[0].t_ns >= last_byte_written[-1] - transcript.start_ns


def test_recv_stamps_a_frame_split_across_writes_when_its_last_part_arrives(
    toy_codec: Codec, transcript: Transcript
) -> None:
    second_part_written: list[int] = []

    async def server(peer: Peer) -> None:
        frame = peer.frame("test:reply", value=7)
        await peer.write(frame[:4])
        await asyncio.sleep(0.02)
        second_part_written.append(await peer.write(frame[4:]))
        await peer.eof()

    async def client() -> int:
        async with (
            serve(toy_codec, server) as endpoint,
            connected(endpoint, toy_codec, transcript) as connection,
        ):
            await connection.recv(timeout_s=1)
            return transcript.now_ns()

    returned = asyncio.run(client())
    [event] = transcript.events
    assert event.packet.fields == {"value": 7}
    assert second_part_written[0] - transcript.start_ns <= event.t_ns <= returned


def test_recv_takes_two_frames_of_one_write_in_order_both_stamped_on_arrival(
    toy_codec: Codec, transcript: Transcript
) -> None:
    async def server(peer: Peer) -> None:
        await peer.write(peer.frame("test:reply", value=1) + peer.frame("test:empty"))
        await peer.eof()

    async def client() -> int:
        async with (
            serve(toy_codec, server) as endpoint,
            connected(endpoint, toy_codec, transcript) as connection,
        ):
            await connection.recv(timeout_s=1)
            await asyncio.sleep(0.02)
            before_second = transcript.now_ns()
            await connection.recv(timeout_s=1)
            return before_second

    before_second = asyncio.run(client())
    first, second = transcript.events
    assert (first.packet.name, second.packet.name) == ("test:reply", "test:empty")
    assert first.t_ns == second.t_ns < before_second


def test_recv_records_a_packet_that_arrived_before_a_send_ahead_of_that_send(
    toy_codec: Codec, transcript: Transcript
) -> None:
    async def server(peer: Peer) -> None:
        await peer.recv()
        await peer.write(peer.frame("test:reply", value=1) + peer.frame("test:empty"))
        await peer.recv()
        await peer.eof()

    async def client() -> None:
        async with (
            serve(toy_codec, server) as endpoint,
            connected(endpoint, toy_codec, transcript) as connection,
        ):
            await connection.send("test:request", value=1)
            await connection.recv(timeout_s=1)
            await asyncio.sleep(0.01)
            await connection.send("test:request", value=2)
            await connection.recv(timeout_s=1)

    asyncio.run(client())
    assert [(event.packet.name, event.packet.fields) for event in transcript.events] == [
        ("test:request", {"value": 1}),
        ("test:reply", {"value": 1}),
        ("test:empty", {}),
        ("test:request", {"value": 2}),
    ]


def test_recv_raises_when_the_server_closes_mid_frame(
    toy_codec: Codec, transcript: Transcript
) -> None:
    async def server(peer: Peer) -> None:
        await peer.write(peer.frame("test:reply", value=7)[:-3])

    async def client() -> None:
        async with (
            serve(toy_codec, server) as endpoint,
            connected(endpoint, toy_codec, transcript) as connection,
        ):
            with pytest.raises(ConnectionClosedError, match=r"mid-frame, 7 byte\(s\) into it"):
                await connection.recv(timeout_s=1)

    asyncio.run(client())
    assert transcript.events == []


def test_recv_raises_when_the_server_closes_between_frames(
    toy_codec: Codec, transcript: Transcript
) -> None:
    async def server(peer: Peer) -> None:
        await peer.send("test:empty")

    async def client() -> None:
        async with (
            serve(toy_codec, server) as endpoint,
            connected(endpoint, toy_codec, transcript) as connection,
        ):
            await connection.recv(timeout_s=1)
            with pytest.raises(ConnectionClosedError, match=r"^the server closed the connection$"):
                await connection.recv(timeout_s=1)

    asyncio.run(client())
    assert [event.packet.name for event in transcript.events] == ["test:empty"]


def test_recv_times_out_and_the_connection_stays_usable(
    toy_codec: Codec, transcript: Transcript
) -> None:
    async def server(peer: Peer) -> None:
        await peer.recv()
        await peer.send("test:reply", value=3)
        await peer.eof()

    async def client() -> Packet:
        async with (
            serve(toy_codec, server) as endpoint,
            connected(endpoint, toy_codec, transcript) as connection,
        ):
            with pytest.raises(TimeoutError):
                await connection.recv(timeout_s=0.05)
            await connection.send("test:request", value=3)
            return await connection.recv(timeout_s=1)

    assert asyncio.run(client()).fields == {"value": 3}


def test_recv_of_a_packet_that_does_not_fit_its_schema_raises_at_once(
    toy_codec: Codec, transcript: Transcript
) -> None:
    async def server(peer: Peer) -> None:
        data = toy_codec.encode(State.HANDSHAKE, Direction.CLIENTBOUND, "test:reply", {"value": 1})
        await peer.write(bytes([len(data) + 1]) + data + b"\x00")  # one byte too many
        await peer.eof()

    async def client() -> None:
        async with (
            serve(toy_codec, server) as endpoint,
            connected(endpoint, toy_codec, transcript) as connection,
        ):
            with pytest.raises(CodecError, match=r"test:reply: 1 unconsumed byte\(s\) remain"):
                await connection.recv(timeout_s=1)

    asyncio.run(client())
    assert transcript.events == []


def test_recv_of_a_corrupt_frame_raises_after_the_frames_before_it(
    toy_codec: Codec, transcript: Transcript
) -> None:
    async def server(peer: Peer) -> None:
        corrupt = bytes.fromhex("80808000")  # a frame length longer than 3 bytes
        await peer.write(peer.frame("test:empty") + corrupt)
        await peer.eof()

    async def client() -> None:
        async with (
            serve(toy_codec, server) as endpoint,
            connected(endpoint, toy_codec, transcript) as connection,
        ):
            assert (await connection.recv(timeout_s=1)).name == "test:empty"
            for _ in range(2):
                with pytest.raises(CodecError, match="frame length VarInt longer than 3 bytes"):
                    await connection.recv(timeout_s=1)

    asyncio.run(client())
    assert [event.packet.name for event in transcript.events] == ["test:empty"]


def test_recv_after_close_raises(toy_codec: Codec, transcript: Transcript) -> None:
    async def server(peer: Peer) -> None:
        await peer.send("test:empty")
        await peer.eof()

    async def client() -> None:
        async with (
            serve(toy_codec, server) as endpoint,
            connected(endpoint, toy_codec, transcript) as connection,
        ):
            await asyncio.sleep(0.01)
            await connection.close()
            with pytest.raises(ConnectionClosedError, match="closed"):
                await connection.recv(timeout_s=1)

    asyncio.run(client())
    assert transcript.events == []
