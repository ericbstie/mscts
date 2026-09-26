"""A fake server for hermetic Connection and Bot tests.

It listens on a free localhost port and speaks just enough protocol, through the
project's own framing and Codec: it decodes serverbound packets and encodes clientbound
ones. It tracks the State on its own (from the intention it receives), so it is an
independent check on the Connection's state machine.
"""

import asyncio
import socket
import struct
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass

from mscts.bot import Bot
from mscts.codec.framing import FrameDecoder, encode_frame
from mscts.codec.packets import Codec, Direction, Packet, State
from mscts.codec.wire import Writer
from mscts.net import Connection, Endpoint
from mscts.target import TARGET
from mscts.transcript import Transcript

HOST = "127.0.0.1"
HANDLER_TIMEOUT_S = 5.0
"""A handler still running after this long fails the test instead of hanging it."""

_READ_SIZE = 65_536
_STATE_BY_INTENT = {1: State.STATUS, 2: State.LOGIN, 3: State.LOGIN}


class Peer:
    """The fake server's end of one connection.

    `state` is the State it reads and writes in: an intention it receives moves it on,
    and a handler moves it on by hand for the later transitions. Frames are compressed
    both ways once `compress` has been called, as vanilla does after login_compression.
    """

    def __init__(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, codec: Codec
    ) -> None:
        self.state = State.HANDSHAKE
        self._reader = reader
        self._writer = writer
        self._codec = codec
        self._frames = FrameDecoder()

    def compress(self, threshold: int) -> None:
        """Use `threshold` from now on, both ways (negative: uncompressed again)."""
        self._frames.compression_threshold = threshold

    async def recv(self) -> Packet:
        """Read the next serverbound Packet, in `state`. An intention moves `state` on.

        Raises EOFError if the client closes the connection first.
        """
        while (frame := self._frames.next_frame()) is None:
            chunk = await self._reader.read(_READ_SIZE)
            if not chunk:
                msg = "the client closed the connection"
                raise EOFError(msg)
            self._frames.extend(chunk)
        packet = self._codec.decode(self.state, Direction.SERVERBOUND, frame)
        if packet.name == "minecraft:intention":
            assert packet.fields is not None
            intent = packet.fields["intent"]
            assert isinstance(intent, int)
            self.state = _STATE_BY_INTENT[intent]
        return packet

    async def packets(self) -> AsyncIterator[Packet]:
        """Yield each serverbound Packet until the client closes the connection."""
        while True:
            try:
                packet = await self.recv()
            except EOFError:
                return
            yield packet

    def frame(self, name: str, /, **fields: object) -> bytes:
        """Encode clientbound packet `name`, in `state`, as one complete frame."""
        data = self._codec.encode(self.state, Direction.CLIENTBOUND, name, fields)
        return encode_frame(data, compression_threshold=self._frames.compression_threshold)

    def raw_frame(self, name: str, payload: bytes = b"") -> bytes:
        """Frame clientbound packet `name`, in `state`, with `payload` as is (no schema)."""
        packet_id = self._codec.packet_id(self.state, Direction.CLIENTBOUND, name)
        data = Writer().var_int(packet_id).to_bytes() + payload
        return encode_frame(data, compression_threshold=self._frames.compression_threshold)

    async def send(self, name: str, /, **fields: object) -> None:
        """Write clientbound packet `name`, in `state`, as one frame."""
        await self.write(self.frame(name, **fields))

    async def write(self, data: bytes) -> int:
        """Write raw bytes, and return the monotonic time just before the write."""
        before = time.monotonic_ns()
        self._writer.write(data)
        await self._writer.drain()
        return before

    async def eof(self) -> None:
        """Wait for the client to close the connection, having sent nothing more."""
        rest = await self._reader.read()
        assert self._frames.buffered == 0
        assert rest == b"", f"the client sent {rest!r} before closing"

    async def reset(self) -> None:
        """Reset the connection (RST) instead of closing it gracefully."""
        sock = self._writer.get_extra_info("socket")
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        self._writer.transport.abort()
        await asyncio.sleep(0)

    async def close(self) -> None:
        """Close the connection gracefully (FIN)."""
        self._writer.close()
        with suppress(ConnectionError):
            await self._writer.wait_closed()


type Handler = Callable[[Peer], Awaitable[None]]
"""What the fake server does with one connection."""

VANILLA_STATUS = {
    "description": "mscts",
    "players": {"max": 20, "online": 0},
    "version": {"name": "26.3", "protocol": 777},
}
"""What vanilla 26.3 answered for the default ServerSpec (docs/research, verified)."""


def status_server(json_response: str, seen: list[Packet]) -> Handler:
    """Answer like vanilla's status listener, putting every serverbound Packet in `seen`.

    A status_request gets `json_response`. A ping_request gets its pong, and then the
    server closes the connection.
    """

    async def handler(peer: Peer) -> None:
        async for packet in peer.packets():
            seen.append(packet)
            if packet.name == "minecraft:status_request":
                await peer.send("minecraft:status_response", json_response=json_response)
            elif packet.name == "minecraft:ping_request":
                assert packet.fields is not None
                await peer.send("minecraft:pong_response", timestamp=packet.fields["timestamp"])
                return

    return handler


CORE_PACK = {"namespace": "minecraft", "id": "core", "version": "26.3"}
"""The one known pack vanilla 26.3 offers in configuration (docs/research, verified)."""

SPAWN = {"x": 6.5, "y": -60.0, "z": 7.5, "yaw": -90.0, "pitch": 0.0}
"""A join teleport's pose (vanilla's is random per fresh world: never assert on it live)."""


@dataclass
class JoinScript:
    """How `join_server` behaves; the defaults follow vanilla 26.3's join (research, verified).

    Attributes:
        compression_threshold: Sent in login_compression, or None to send none.
        code_of_conduct: Sent (and its acceptance awaited) in configuration, or None.
        keep_alive_id: Sent (and its echo awaited) once the first chunk batch is
            acknowledged, or None.
        disconnect_in: The State in which to disconnect the client instead of going on.
        then: Run last, before waiting for the client to close, or None.
    """

    compression_threshold: int | None = 256
    code_of_conduct: str | None = None
    keep_alive_id: int | None = None
    disconnect_in: State | None = None
    then: Handler | None = None


_DISCONNECT_REASON = bytes.fromhex("08 0004") + b"kick"  # an NBT String text component


def join_server(seen: list[Packet], script: JoinScript | None = None) -> Handler:
    """Answer like vanilla's login, configuration and play listeners, up to one chunk batch.

    Every serverbound Packet goes into `seen`. Each step waits for the answer vanilla's
    server waits for (or, like it, simply goes on), so a client that does not answer
    stalls here as it would against vanilla.
    """
    join = _Join(seen, script or JoinScript())

    async def handler(peer: Peer) -> None:
        if await join.login(peer) and await join.configure(peer) and await join.play(peer):
            if join.script.then is not None:
                await join.script.then(peer)
            await peer.eof()

    return handler


class _Join:
    """`join_server`'s steps: each returns False if it disconnected the client instead."""

    def __init__(self, seen: list[Packet], script: JoinScript) -> None:
        self.seen = seen
        self.script = script

    async def expect(self, peer: Peer, name: str) -> Packet:
        packet = await peer.recv()
        self.seen.append(packet)
        assert packet.name == name, f"expected {name}, got {packet.name}"
        return packet

    async def login(self, peer: Peer) -> bool:
        await self.expect(peer, "minecraft:intention")
        hello = await self.expect(peer, "minecraft:hello")
        assert hello.fields is not None
        if self.script.disconnect_in is State.LOGIN:
            await peer.write(peer.raw_frame("minecraft:login_disconnect", b'\x06"kick"'))
            return False
        threshold = self.script.compression_threshold
        if threshold is not None:
            await peer.write(peer.frame("minecraft:login_compression", threshold=threshold))
            peer.compress(threshold)
        profile = {"uuid": hello.fields["player_uuid"], "username": hello.fields["name"]}
        await peer.send(
            "minecraft:login_finished",
            profile={**profile, "properties": []},
            session_id=uuid.UUID(int=1),
        )
        await self.expect(peer, "minecraft:login_acknowledged")
        peer.state = State.CONFIGURATION
        return True

    async def configure(self, peer: Peer) -> bool:
        if self.script.disconnect_in is State.CONFIGURATION:
            await peer.send("minecraft:disconnect", reason=_DISCONNECT_REASON)
            return False
        await peer.send("minecraft:custom_payload", channel="minecraft:brand", data=b"\x07vanilla")
        await peer.send("minecraft:update_enabled_features", feature_flags=["minecraft:vanilla"])
        await peer.send("minecraft:select_known_packs", known_packs=[CORE_PACK])
        echoed = await self.expect(peer, "minecraft:select_known_packs")
        assert echoed.fields == {"known_packs": [CORE_PACK]}
        entries = [{"entry_id": "minecraft:overworld", "data": None}]
        await peer.send(
            "minecraft:registry_data", registry_id="minecraft:dimension_type", entries=entries
        )
        await peer.send("minecraft:update_tags", tagged_registries=[])
        if self.script.code_of_conduct is not None:
            await peer.send(
                "minecraft:code_of_conduct", code_of_conduct=self.script.code_of_conduct
            )
            await self.expect(peer, "minecraft:accept_code_of_conduct")
        await peer.send("minecraft:finish_configuration")
        await self.expect(peer, "minecraft:finish_configuration")
        peer.state = State.PLAY
        return True

    async def play(self, peer: Peer) -> bool:
        if self.script.disconnect_in is State.PLAY:
            await peer.send("minecraft:disconnect", reason=_DISCONNECT_REASON)
            return False
        await peer.write(peer.raw_frame("minecraft:change_difficulty", b"\x00\x01"))
        await peer.send(
            "minecraft:player_position",
            teleport_id=1,
            velocity_x=0.0,
            velocity_y=0.0,
            velocity_z=0.0,
            flags=0,
            **SPAWN,
        )
        await self.expect(peer, "minecraft:accept_teleportation")
        await peer.send("minecraft:chunk_batch_start")
        await peer.write(peer.raw_frame("minecraft:level_chunk_with_light", bytes(300)))
        await peer.send("minecraft:chunk_batch_finished", batch_size=1)
        await self.expect(peer, "minecraft:chunk_batch_received")
        if self.script.keep_alive_id is not None:
            await peer.send("minecraft:keep_alive", keep_alive_id=self.script.keep_alive_id)
            await self.expect(peer, "minecraft:keep_alive")
        return True


@asynccontextmanager
async def serve(codec: Codec, handler: Handler) -> AsyncIterator[Endpoint]:
    """Listen on a free localhost port, running `handler` for each connection.

    A handler that raises fails the test from inside the `async with` body. Leaving
    the body waits for every handler to finish, so a handler's last checks always run.
    A single error, from the body or a handler, comes out as itself rather than
    inside an ExceptionGroup, so `pytest.raises` around `serve` works.
    """
    try:
        async with asyncio.TaskGroup() as handlers:

            def on_connect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
                handlers.create_task(_run(handler, Peer(reader, writer, codec)))

            server = await asyncio.start_server(on_connect, HOST, 0)
            try:
                yield Endpoint(host=HOST, port=server.sockets[0].getsockname()[1])
            finally:
                server.close()
    except ExceptionGroup as group:
        if len(group.exceptions) == 1:
            raise group.exceptions[0] from None
        raise
    await server.wait_closed()


@asynccontextmanager
async def connected(
    endpoint: Endpoint, codec: Codec, transcript: Transcript, *, bot: str = "alice"
) -> AsyncIterator[Connection]:
    """Open a Connection, and close it however the body ends.

    A test that fails with its Connection open would otherwise leak the socket into
    the next test, which then fails on the ResourceWarning.
    """
    connection = await Connection.open(endpoint, codec, bot=bot, transcript=transcript)
    try:
        yield connection
    finally:
        await connection.close()


def with_bot[T](
    codec: Codec,
    transcript: Transcript,
    handler: Handler,
    use: Callable[[Bot], Awaitable[T]],
    *,
    timeout_s: float = 1.0,
) -> tuple[T, Endpoint]:
    """Run `use` on a Bot named alice connected to a fake server running `handler`."""

    async def client() -> tuple[T, Endpoint]:
        async with serve(codec, handler) as endpoint:
            bot = await Bot.connect(
                endpoint, TARGET, name="alice", transcript=transcript, timeout_s=timeout_s
            )
            try:
                return await use(bot), endpoint
            finally:
                await bot.close()

    return asyncio.run(client())


def free_port() -> int:
    """Return a localhost port nothing listens on (it was free a moment ago)."""
    with socket.socket() as sock:
        sock.bind((HOST, 0))
        port = sock.getsockname()[1]
    assert isinstance(port, int)
    return port


async def _run(handler: Handler, peer: Peer) -> None:
    try:
        async with asyncio.timeout(HANDLER_TIMEOUT_S):
            await handler(peer)
    finally:
        await peer.close()
