"""Reaching a server over the network: Endpoints and Connections."""

import asyncio
import contextlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Self

from mscts.codec.framing import FrameDecoder, encode_frame
from mscts.codec.packets import Codec, CodecError, Direction, Packet, State
from mscts.codec.wire import WireError
from mscts.transcript import Transcript

_READ_SIZE = 65_536
"""The most bytes one read of the background reader takes from the socket."""

_CLOSE_TIMEOUT_S = 1.0
"""How long close() waits for the socket to finish closing before aborting it."""

_STATE_BY_INTENT: Mapping[int, State] = {1: State.STATUS, 2: State.LOGIN, 3: State.LOGIN}
"""Where the handshake `intention` leads: 1 = status, 2 = login, 3 = transfer (a login)."""

_STATE_AFTER: Mapping[tuple[State, str], State] = {
    (State.LOGIN, "minecraft:login_acknowledged"): State.CONFIGURATION,
    (State.CONFIGURATION, "minecraft:finish_configuration"): State.PLAY,
}
"""The other serverbound packets that move a connection to a new State."""


@dataclass(frozen=True, slots=True)
class Endpoint:
    """Where an Instance can be reached."""

    host: str
    port: int


class ConnectionClosedError(ConnectionError):
    """The Connection is closed: the server closed it, or `close()` was called."""


class ProtocolError(Exception):
    """A packet that breaks the protocol's sequence, e.g. an intention with an unknown intent."""


@dataclass(frozen=True, slots=True)
class _Arrival:
    """A frame the background reader decoded, and when the read that completed it returned."""

    t_ns: int
    packet: Packet


@dataclass(frozen=True, slots=True)
class _End:
    """The background reader stopped, or the Connection closed: `recv` raises `error`."""

    error: Exception


class Connection:
    """One TCP connection to a server. It owns the framing and the State.

    The State starts at handshake and moves on when the Connection sends an
    `intention` (to status or login, by its intent), `login_acknowledged` (to
    configuration) or `finish_configuration` (to play). Both directions change
    together: every later frame is encoded, and decoded when it arrives, in the new
    State.

    A background reader reads the socket continuously from `open` until `close`. It
    stamps each frame when the read that completed it returns, decodes it, and queues
    it for `recv`, so a frame's time is when it arrived, not when it was taken.

    Every Packet it sends or receives is recorded to its Transcript as an Event of
    its Bot:

    - A sent Packet is stamped immediately before its frame is written to the
      socket, and it is recorded as decoded from the exact bytes written.
    - A received Packet is recorded when `recv` returns it, with its arrival stamp.
      So the Transcript holds the frames the Bot took, whatever the TCP segmentation,
      and frames that arrived together keep the time they arrived, however late they
      are taken.
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
        """Wrap an open stream pair, and start reading it. Use `open` to connect."""
        self._reader = reader
        self._writer = writer
        self._codec = codec
        self._bot = bot
        self._transcript = transcript
        self._state = State.HANDSHAKE
        self._frames = FrameDecoder()
        self._arrivals: asyncio.Queue[_Arrival | _End] = asyncio.Queue()
        self._end: _End | None = None
        self._closed = False
        self._reading = asyncio.get_running_loop().create_task(
            self._read_forever(), name=f"mscts Connection reader ({bot})"
        )

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
            ProtocolError: It is an intention with an unknown intent.
            ConnectionClosedError: The Connection is closed, or the connection was lost.

            In each case nothing is written or recorded, and the State stays.
        """
        self._check_open()
        data = self._codec.encode(self._state, Direction.SERVERBOUND, name, fields)
        packet = self._codec.decode(self._state, Direction.SERVERBOUND, data)
        state_after = _state_after(packet)
        frame = encode_frame(data, compression_threshold=self._frames.compression_threshold)
        if self._writer.transport.is_closing():
            # asyncio's write() would silently discard the frame.
            msg = "the connection was lost"
            raise ConnectionClosedError(msg)
        t_ns = self._transcript.now_ns()
        self._writer.write(frame)
        self._transcript.record(self._bot, packet, t_ns=t_ns)
        self._state = state_after
        await self._writer.drain()

    async def recv(self, *, timeout_s: float) -> Packet:
        """Take the next clientbound Packet the background reader decoded, and record it.

        Raises:
            TimeoutError: No complete frame arrived within `timeout_s` seconds. The
                Connection stays usable.
            CodecError: The frame is corrupt, or its packet is unknown or does not fit
                its schema exactly. Nothing is recorded, and the reader has stopped.
            ConnectionClosedError: The Connection is closed, or the server closed it
                (the message says if that was mid-frame).
            ConnectionResetError: The server reset the connection.

            Once the reader has stopped, every later call raises the same error.
        """
        self._check_open()
        if self._end is not None and self._arrivals.empty():
            raise self._end.error
        async with asyncio.timeout(timeout_s):
            item = await self._arrivals.get()
        if isinstance(item, _End):
            self._end = item
            raise item.error
        self._transcript.record(self._bot, item.packet, t_ns=item.t_ns)
        return item.packet

    async def close(self) -> None:
        """Stop the reader and close the connection. Calling it again does nothing.

        A `recv` still waiting raises ConnectionClosedError. If the socket has not
        finished closing within a second (a server that stops reading can hold unsent
        bytes back), it is aborted.
        """
        if self._closed:
            return
        self._closed = True
        self._reading.cancel()
        await asyncio.wait({self._reading})
        self._arrivals.put_nowait(_End(ConnectionClosedError("the connection is closed")))
        self._writer.close()
        with contextlib.suppress(ConnectionError):
            try:
                async with asyncio.timeout(_CLOSE_TIMEOUT_S):
                    await self._writer.wait_closed()
            except TimeoutError:
                self._writer.transport.abort()

    async def _read_forever(self) -> None:
        """Read, stamp, decode and queue every frame, until the stream ends or fails."""
        try:
            while True:
                chunk = await self._reader.read(_READ_SIZE)
                t_ns = self._transcript.now_ns()
                if not chunk:
                    self._arrivals.put_nowait(self._end_of_stream())
                    return
                self._frames.extend(chunk)
                while (frame := self._take_frame()) is not None:
                    packet = self._codec.decode(self._state, Direction.CLIENTBOUND, frame)
                    self._arrivals.put_nowait(_Arrival(t_ns=t_ns, packet=packet))
        except Exception as exc:  # noqa: BLE001 - not swallowed: recv raises it
            # Whatever stopped the reader (the server, a corrupt frame, or a harness bug)
            # is raised by recv, rather than lost in a task nobody awaits.
            self._arrivals.put_nowait(_End(exc))

    def _end_of_stream(self) -> _End:
        if self._frames.buffered:
            msg = (
                "the server closed the connection mid-frame, "
                f"{self._frames.buffered} byte(s) into it"
            )
        else:
            msg = "the server closed the connection"
        return _End(ConnectionClosedError(msg))

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


def _state_after(packet: Packet) -> State:
    """Return the State a connection is in once it has sent `packet`.

    Raises:
        ProtocolError: `packet` is an intention with an unknown intent.
    """
    if packet.state is State.HANDSHAKE and packet.name == "minecraft:intention":
        intent = (packet.fields or {}).get("intent")
        if not isinstance(intent, int) or intent not in _STATE_BY_INTENT:
            msg = f"unknown intent {intent!r} (1 = status, 2 = login, 3 = transfer)"
            raise ProtocolError(msg)
        return _STATE_BY_INTENT[intent]
    return _STATE_AFTER.get((packet.state, packet.name), packet.state)
