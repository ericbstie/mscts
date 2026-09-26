"""Reaching a server over the network: Endpoints and Connections."""

import asyncio
import contextlib
from dataclasses import dataclass
from typing import Self

from mscts.codec.framing import FrameDecoder, encode_frame
from mscts.codec.packets import Codec, Direction, State
from mscts.transcript import Transcript

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
    its Bot. A sent Packet is stamped immediately before its frame is written to the
    socket, and it is recorded as decoded from the exact bytes written.
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
            ConnectionClosedError: The Connection is closed.
        """
        self._check_open()
        data = self._codec.encode(self._state, Direction.SERVERBOUND, name, fields)
        packet = self._codec.decode(self._state, Direction.SERVERBOUND, data)
        frame = encode_frame(data, compression_threshold=self._frames.compression_threshold)
        t_ns = self._transcript.now_ns()
        self._writer.write(frame)
        self._transcript.record(self._bot, packet, t_ns=t_ns)
        await self._writer.drain()

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

    def _check_open(self) -> None:
        if self._closed:
            msg = "the connection is closed"
            raise ConnectionClosedError(msg)
