"""Reaching a server over the network: Endpoints and Connections."""

import asyncio
import contextlib
from dataclasses import dataclass
from typing import Self

from mscts.codec.framing import FrameDecoder, encode_frame
from mscts.codec.packets import Codec, CodecError, Direction, Packet, State
from mscts.codec.wire import WireError
from mscts.transcript import Transcript

_READ_SIZE = 65_536
"""The most bytes one read takes from the socket."""

_CLOSE_TIMEOUT_S = 1.0
"""How long close() waits for the socket to finish closing before aborting it."""


@dataclass(frozen=True, slots=True)
class Endpoint:
    """Where an Instance can be reached."""

    host: str
    port: int


class ConnectionClosedError(ConnectionError):
    """The Connection is closed: the server closed it, or `close()` was called."""


class Connection:
    """One TCP connection to a server. It owns the framing and the State.

    Every Packet it sends or receives is recorded to its Transcript as an Event of
    its Bot:

    - A sent Packet is stamped immediately before its frame is written to the
      socket, and it is recorded as decoded from the exact bytes written.
    - A received Packet is stamped when the socket read that completed its frame
      returned, and it is recorded when `recv` returns it. Frames that arrive
      together keep the time they arrived, however late they are taken.
    """

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        codec: Codec,
        *,
        bot: str,
        transcript: Transcript,
    ) -> None:
        """Wrap an open stream pair. Use `open` to connect."""
        self._reader = reader
        self._writer = writer
        self._codec = codec
        self._bot = bot
        self._transcript = transcript
        self._state = State.HANDSHAKE
        self._frames = FrameDecoder()
        # When the latest socket read returned. recv reads only while no complete frame
        # is buffered, so every frame it takes was completed by that read.
        self._last_read_ns = 0
        self._closed = False

    @classmethod
    async def open(
        cls, endpoint: Endpoint, codec: Codec, *, bot: str, transcript: Transcript
    ) -> Self:
        """Connect to `endpoint`, in the handshake State, recording as `bot`.

        asyncio turns Nagle's algorithm off (TCP_NODELAY), so small frames are
        written at once rather than held back for coalescing.

        Raises:
            OSError: The connection failed, e.g. ConnectionRefusedError.
        """
        reader, writer = await asyncio.open_connection(endpoint.host, endpoint.port)
        return cls(reader, writer, codec, bot=bot, transcript=transcript)

    @property
    def state(self) -> State:
        """The connection State both directions are currently in."""
        return self._state

    async def send(self, name: str, /, **fields: object) -> None:
        """Encode serverbound packet `name` with `fields` in the current State, and send it.

        Raises:
            CodecError: The packet is unknown here, or `fields` do not fit its schema.
                Nothing is written or recorded.
            ConnectionClosedError: The Connection is closed, or the connection was lost
                (nothing is written or recorded).
        """
        self._check_open()
        data = self._codec.encode(self._state, Direction.SERVERBOUND, name, fields)
        packet = self._codec.decode(self._state, Direction.SERVERBOUND, data)
        frame = encode_frame(data, compression_threshold=self._frames.compression_threshold)
        if self._writer.transport.is_closing():
            # asyncio's write() would silently discard the frame.
            msg = "the connection was lost"
            raise ConnectionClosedError(msg)
        t_ns = self._transcript.now_ns()
        self._writer.write(frame)
        self._transcript.record(self._bot, packet, t_ns=t_ns)
        await self._writer.drain()

    async def recv(self, *, timeout_s: float) -> Packet:
        """Receive the next clientbound Packet, decoded in the current State.

        Raises:
            TimeoutError: No complete frame arrived within `timeout_s` seconds. The
                Connection stays usable.
            CodecError: The frame is corrupt, or its packet is unknown here or does not
                fit its schema exactly. Nothing is recorded.
            ConnectionClosedError: The Connection is closed, or the server closed it
                (the message says if that was mid-frame).
        """
        self._check_open()
        async with asyncio.timeout(timeout_s):
            while (frame := self._take_frame()) is None:
                await self._read()
        packet = self._codec.decode(self._state, Direction.CLIENTBOUND, frame)
        self._transcript.record(self._bot, packet, t_ns=self._last_read_ns)
        return packet

    async def close(self) -> None:
        """Close the connection. Calling it again does nothing.

        If the socket has not finished closing within a second (a server that stops
        reading can hold unsent bytes back), it is aborted.
        """
        if self._closed:
            return
        self._closed = True
        self._writer.close()
        with contextlib.suppress(ConnectionError):
            try:
                async with asyncio.timeout(_CLOSE_TIMEOUT_S):
                    await self._writer.wait_closed()
            except TimeoutError:
                self._writer.transport.abort()

    async def _read(self) -> None:
        chunk = await self._reader.read(_READ_SIZE)
        t_ns = self._transcript.now_ns()
        if not chunk:
            if self._frames.buffered:
                msg = (
                    "the server closed the connection mid-frame, "
                    f"{self._frames.buffered} byte(s) into it"
                )
            else:
                msg = "the server closed the connection"
            raise ConnectionClosedError(msg)
        self._frames.extend(chunk)
        self._last_read_ns = t_ns

    def _take_frame(self) -> bytes | None:
        try:
            return self._frames.next_frame()
        except WireError as exc:
            msg = f"{self._state} {Direction.CLIENTBOUND} frame: {exc}"
            raise CodecError(msg) from exc

    def _check_open(self) -> None:
        if self._closed:
            msg = "the connection is closed"
            raise ConnectionClosedError(msg)
