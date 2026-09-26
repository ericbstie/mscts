"""Connection transport: framing, recording and timestamps, over a fake localhost server.

These use the handshake-only `toy_codec`, so no State changes are involved.
"""

import asyncio
import contextlib
import socket
import struct
import threading
import time
from collections.abc import Callable, Iterator

import pytest

from mscts import net
from mscts.codec.packets import Codec, CodecError, Direction, Packet, State, UnknownPacketError
from mscts.net import Connection, ConnectionClosedError, Endpoint, ProtocolError
from mscts.transcript import Event, Transcript
from tests.net.fakes import HOST, Peer, connected, serve


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
    toy_codec: Codec, transcript: Transcript, stream_writers: list[asyncio.StreamWriter]
) -> None:
    async def server(peer: Peer) -> None:
        await peer.eof()

    async def client() -> None:
        async with serve(toy_codec, server) as endpoint, connected(endpoint, toy_codec, transcript):
            sock = stream_writers[0].get_extra_info("socket")
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


def test_send_after_the_server_reset_the_connection_raises_and_records_nothing(
    toy_codec: Codec, transcript: Transcript
) -> None:
    # asyncio's write() silently discards data once the connection is lost, so the
    # Connection must refuse rather than record a Packet that never left.
    async def server(peer: Peer) -> None:
        await peer.reset()

    async def client() -> None:
        async with (
            serve(toy_codec, server) as endpoint,
            connected(endpoint, toy_codec, transcript) as connection,
        ):
            with pytest.raises(ConnectionResetError):
                await connection.recv(timeout_s=1)
            with pytest.raises(ConnectionClosedError, match="the connection was lost"):
                await connection.send("test:request", value=7)

    asyncio.run(client())
    assert transcript.events == []


@contextlib.contextmanager
def resetting_server() -> Iterator[tuple[Endpoint, Callable[[], None]]]:
    """A plain-socket server, off the event loop, that resets its first connection on cue.

    Yields its Endpoint and `reset`: once the client has connected, `reset()` makes the
    server reset (SO_LINGER 0, then close) and blocks the caller's thread, and so its
    event loop, until the RST has reached the client, which has therefore not seen it.
    """
    listener = socket.create_server((HOST, 0))
    cue, done = threading.Event(), threading.Event()

    def accept_and_reset() -> None:
        sock, _ = listener.accept()
        cue.wait(timeout=5)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        sock.close()
        done.set()

    def reset() -> None:
        cue.set()
        assert done.wait(timeout=5)
        time.sleep(0.05)  # loopback delivers the RST at once; the loop stays blocked

    thread = threading.Thread(target=accept_and_reset, daemon=True)
    thread.start()
    try:
        yield Endpoint(host=HOST, port=listener.getsockname()[1]), reset
    finally:
        cue.set()
        listener.close()
        thread.join(timeout=5)


def test_a_send_whose_write_fails_raises_records_nothing_and_keeps_the_state(
    codec: Codec, transcript: Transcript
) -> None:
    # Audit MD2: the reset was only seen once the write failed, after the Packet was
    # recorded and the State advanced, and it raised ConnectionResetError.
    async def client() -> State:
        with resetting_server() as (endpoint, reset):
            async with connected(endpoint, codec, transcript) as connection:
                reset()
                with pytest.raises(ConnectionClosedError, match="the connection was lost"):
                    await connection.send(
                        "minecraft:intention",
                        protocol_version=777,
                        server_address=HOST,
                        server_port=endpoint.port,
                        intent=1,
                    )
                return connection.state

    assert asyncio.run(client()) is State.HANDSHAKE
    assert transcript.events == []


def test_send_records_and_returns_only_once_the_write_has_drained(
    toy_codec: Codec,
    transcript: Transcript,
    stream_writers: list[asyncio.StreamWriter],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Audit N13: a server that stops reading must hold send back (backpressure), and a
    # Packet is recorded only once its write has drained.
    drained = asyncio.Event()

    async def server(peer: Peer) -> None:
        await peer.recv()
        await peer.eof()

    async def client() -> list[bool]:
        async with (
            serve(toy_codec, server) as endpoint,
            connected(endpoint, toy_codec, transcript) as connection,
        ):
            [writer] = stream_writers
            drain = writer.drain

            async def slow_drain() -> None:
                await drained.wait()
                await drain()

            monkeypatch.setattr(writer, "drain", slow_drain)
            sending = asyncio.create_task(connection.send("test:request", value=1))
            await asyncio.sleep(0.05)
            seen = [sending.done(), bool(transcript.events)]
            drained.set()
            await sending
            return [*seen, sending.done(), bool(transcript.events)]

    assert asyncio.run(client()) == [False, False, True, True]


def test_a_send_cancelled_while_draining_still_records_its_queued_frame(
    toy_codec: Codec,
    transcript: Transcript,
    stream_writers: list[asyncio.StreamWriter],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The frame is already in the transport's buffer, so it goes out once the server reads:
    # leaving it out of the Transcript (or the State behind) would misreport the wire.
    received: list[Packet] = []

    async def server(peer: Peer) -> None:
        received.append(await peer.recv())
        await peer.eof()

    async def client() -> None:
        async with (
            serve(toy_codec, server) as endpoint,
            connected(endpoint, toy_codec, transcript) as connection,
        ):
            [writer] = stream_writers

            async def never_drains() -> None:
                await asyncio.Event().wait()

            monkeypatch.setattr(writer, "drain", never_drains)
            with pytest.raises(TimeoutError):
                async with asyncio.timeout(0.05):
                    await connection.send("test:request", value=1)

    asyncio.run(client())
    assert [event.packet.fields for event in transcript.events] == [{"value": 1}]
    assert [packet.fields for packet in received] == [{"value": 1}]


def test_close_aborts_a_socket_that_does_not_finish_closing(
    toy_codec: Codec,
    transcript: Transcript,
    stream_writers: list[asyncio.StreamWriter],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A server that stops reading can hold unsent bytes back, so wait_closed() never
    # returns. Simulate that on the client's writer only, with close()'s grace period
    # shortened.
    aborted: list[bool] = []

    async def never() -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(net, "_CLOSE_TIMEOUT_S", 0.05)

    async def server(peer: Peer) -> None:
        await peer.eof()

    async def client() -> None:
        async with serve(toy_codec, server) as endpoint:
            connection = await Connection.open(
                endpoint, toy_codec, bot="alice", transcript=transcript
            )
            [writer] = stream_writers
            abort = writer.transport.abort
            monkeypatch.setattr(writer, "wait_closed", never)
            monkeypatch.setattr(writer.transport, "abort", lambda: (aborted.append(True), abort()))
            async with asyncio.timeout(1):
                await connection.close()

    asyncio.run(client())
    assert aborted == [True]


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


def test_a_reply_that_arrives_while_the_caller_is_busy_is_stamped_when_it_arrived(
    toy_codec: Codec, transcript: Transcript
) -> None:
    # Audit H2: the stamp was the time recv got round to reading, 300 ms late here.
    written: list[int] = []

    async def server(peer: Peer) -> None:
        await peer.recv()
        written.append(await peer.write(peer.frame("test:reply", value=1)))
        await peer.eof()

    async def client() -> None:
        async with (
            serve(toy_codec, server) as endpoint,
            connected(endpoint, toy_codec, transcript) as connection,
        ):
            await connection.send("test:request", value=1)
            await asyncio.sleep(0.3)  # busy elsewhere, e.g. another Bot or a Control command
            await connection.recv(timeout_s=1)

    asyncio.run(client())
    request, reply = transcript.events
    assert reply.packet.name == "test:reply"
    assert written[0] - transcript.start_ns <= reply.t_ns < request.t_ns + 50_000_000


def test_close_ends_the_background_reader(toy_codec: Codec, transcript: Transcript) -> None:
    async def server(peer: Peer) -> None:
        await peer.eof()

    async def client() -> list[tuple[bool, bool]]:
        async with serve(toy_codec, server) as endpoint:
            connection = await Connection.open(
                endpoint, toy_codec, bot="alice", transcript=transcript
            )
            readers = [task for task in asyncio.all_tasks() if "reader" in task.get_name()]
            await connection.close()
            return [(task.done(), task.cancelled()) for task in readers]

    # One reader, and close() leaves it finished (not merely asked to stop).
    assert asyncio.run(client()) == [(True, True)]


def test_an_unexpected_error_in_the_reader_is_raised_by_recv(
    toy_codec: Codec, transcript: Transcript, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A harness bug must surface at the next recv, not vanish in a task nobody awaits.

    def broken_decode(*args: object) -> Packet:
        del args
        msg = "a bug in a wire type"
        raise RuntimeError(msg)

    async def server(peer: Peer) -> None:
        await peer.send("test:empty")
        await peer.eof()

    async def client() -> None:
        async with (
            serve(toy_codec, server) as endpoint,
            connected(endpoint, toy_codec, transcript) as connection,
        ):
            monkeypatch.setattr(toy_codec, "decode", broken_decode)  # before the reader runs
            for _ in range(2):
                with pytest.raises(RuntimeError, match="a bug in a wire type"):
                    await connection.recv(timeout_s=1)

    asyncio.run(client())
    assert transcript.events == []


async def echo_replies(connection: Connection, packet: Packet) -> None:
    """An answer: each test:reply is echoed back as a test:request with the same value."""
    if packet.name == "test:reply":
        assert packet.fields is not None
        await connection.send("test:request", value=packet.fields["value"])


def test_the_answer_runs_as_each_packet_arrives_without_a_recv(
    toy_codec: Codec, transcript: Transcript
) -> None:
    # What keeps a Bot connected (keep-alives, teleports) must not wait for a Scenario to
    # take the packet: vanilla kicks a client that does not answer a keep_alive in time.
    echoed: list[Packet] = []

    async def server(peer: Peer) -> None:
        await peer.write(peer.frame("test:reply", value=1) + peer.frame("test:reply", value=2))
        echoed.extend([await peer.recv(), await peer.recv()])
        await peer.send("test:empty")
        await peer.eof()

    async def client() -> list[str]:
        async with serve(toy_codec, server) as endpoint:
            connection = await Connection.open(
                endpoint, toy_codec, bot="alice", transcript=transcript, answer=echo_replies
            )
            try:
                return [(await connection.recv(timeout_s=1)).name for _ in range(3)]
            finally:
                await connection.close()

    assert asyncio.run(client()) == ["test:reply", "test:reply", "test:empty"]
    assert [packet.fields for packet in echoed] == [{"value": 1}, {"value": 2}]
    # Each answer is recorded after the packet it answers: that arrived first.
    assert [(event.packet.name, event.packet.fields) for event in transcript.events] == [
        ("test:reply", {"value": 1}),
        ("test:reply", {"value": 2}),
        ("test:request", {"value": 1}),
        ("test:request", {"value": 2}),
        ("test:empty", {}),
    ]


def test_an_answer_that_fails_stops_the_reader_after_the_packet_it_answered(
    toy_codec: Codec, transcript: Transcript
) -> None:
    async def refuse(connection: Connection, packet: Packet) -> None:
        del connection
        msg = f"cannot answer {packet.name}"
        raise ProtocolError(msg)

    async def server(peer: Peer) -> None:
        await peer.write(peer.frame("test:reply", value=1) + peer.frame("test:empty"))
        await peer.eof()

    async def client() -> None:
        async with serve(toy_codec, server) as endpoint:
            connection = await Connection.open(
                endpoint, toy_codec, bot="alice", transcript=transcript, answer=refuse
            )
            try:
                assert (await connection.recv(timeout_s=1)).name == "test:reply"
                for _ in range(2):
                    with pytest.raises(ProtocolError, match="cannot answer test:reply"):
                        await connection.recv(timeout_s=1)
            finally:
                await connection.close()

    asyncio.run(client())
    assert [event.packet.name for event in transcript.events] == ["test:reply"]


def test_an_answer_that_finds_the_connection_lost_lets_the_reader_read_on(
    toy_codec: Codec, transcript: Transcript
) -> None:
    # The server may have closed right after its last packets (a disconnect reason, say):
    # those must still reach recv, even though answering the first one failed.
    async def lost(connection: Connection, packet: Packet) -> None:
        del connection, packet
        msg = "the connection was lost"
        raise ConnectionClosedError(msg)

    async def server(peer: Peer) -> None:
        await peer.write(peer.frame("test:reply", value=1) + peer.frame("test:empty"))

    async def client() -> list[str]:
        async with serve(toy_codec, server) as endpoint:
            connection = await Connection.open(
                endpoint, toy_codec, bot="alice", transcript=transcript, answer=lost
            )
            try:
                names = [(await connection.recv(timeout_s=1)).name for _ in range(2)]
                with pytest.raises(ConnectionClosedError, match="the server closed"):
                    await connection.recv(timeout_s=1)
                return names
            finally:
                await connection.close()

    assert asyncio.run(client()) == ["test:reply", "test:empty"]


def test_close_wakes_a_pending_recv(toy_codec: Codec, transcript: Transcript) -> None:
    async def server(peer: Peer) -> None:
        await peer.eof()

    async def client() -> None:
        async with (
            serve(toy_codec, server) as endpoint,
            connected(endpoint, toy_codec, transcript) as connection,
        ):
            pending = asyncio.create_task(connection.recv(timeout_s=5))
            await asyncio.sleep(0.01)
            await connection.close()
            with pytest.raises(ConnectionClosedError, match="the connection is closed"):
                await pending

    asyncio.run(client())
    assert transcript.events == []


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


def test_a_packet_that_does_not_fit_its_schema_is_recorded_before_recv_raises(
    toy_codec: Codec, transcript: Transcript
) -> None:
    # Audit H3: a Candidate's malformed packet must become evidence, not a silent gap.
    async def server(peer: Peer) -> None:
        data = toy_codec.encode(State.HANDSHAKE, Direction.CLIENTBOUND, "test:reply", {"value": 1})
        await peer.write(bytes([len(data) + 1]) + data + b"\x00")  # one byte too many
        await peer.send("test:empty")  # never delivered: the reader stopped, as vanilla does
        await peer.eof()

    async def client() -> None:
        async with (
            serve(toy_codec, server) as endpoint,
            connected(endpoint, toy_codec, transcript) as connection,
        ):
            for _ in range(2):
                with pytest.raises(CodecError, match=r"test:reply: 1 unconsumed byte\(s\) remain"):
                    await connection.recv(timeout_s=1)

    asyncio.run(client())
    [event] = transcript.events
    assert event.packet == Packet(
        state=State.HANDSHAKE,
        direction=Direction.CLIENTBOUND,
        name="test:reply",
        packet_id=0x00,
        payload=(1).to_bytes(8, "big") + b"\x00",
        fields=None,
        decode_error="handshake clientbound test:reply: 1 unconsumed byte(s) remain",
    )


def test_a_packet_with_an_unknown_id_is_recorded_before_recv_raises(
    toy_codec: Codec, transcript: Transcript
) -> None:
    async def server(peer: Peer) -> None:
        await peer.write(bytes.fromhex("03 2a 0102"))  # id 0x2a, then 2 payload bytes
        await peer.eof()

    async def client() -> None:
        async with (
            serve(toy_codec, server) as endpoint,
            connected(endpoint, toy_codec, transcript) as connection,
        ):
            with pytest.raises(UnknownPacketError, match="no packet handshake clientbound 0x2a"):
                await connection.recv(timeout_s=1)

    asyncio.run(client())
    [event] = transcript.events
    assert (event.packet.name, event.packet.packet_id, event.packet.payload) == (
        "unknown:handshake:0x2a",
        0x2A,
        bytes.fromhex("0102"),
    )
    assert event.packet.decode_error == "no packet handshake clientbound 0x2a"


def test_a_corrupt_frame_is_recorded_after_the_frames_before_it(
    toy_codec: Codec, transcript: Transcript
) -> None:
    written: list[int] = []

    async def server(peer: Peer) -> None:
        corrupt = bytes.fromhex("80808000")  # a frame length longer than 3 bytes
        written.append(await peer.write(peer.frame("test:empty") + corrupt))
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
    assert [event.packet.name for event in transcript.events] == ["test:empty", "corrupt:handshake"]
    corrupt = transcript.events[1]
    assert (corrupt.packet.packet_id, corrupt.packet.payload) == (-1, bytes.fromhex("808080"))
    assert corrupt.packet.decode_error == (
        "handshake clientbound frame: frame length VarInt longer than 3 bytes"
    )
    assert corrupt.t_ns >= written[0] - transcript.start_ns  # stamped on arrival too


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
