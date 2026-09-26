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
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress

from mscts.codec.framing import FrameDecoder, encode_frame
from mscts.codec.packets import Codec, Direction, Packet, State
from mscts.codec.wire import Writer
from mscts.net import Connection, Endpoint
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
