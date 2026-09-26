"""Reaching a server over the network: Endpoints and Connections."""

import asyncio
import contextlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Self

from mscts.codec.framing import FrameDecoder, FrameError, encode_frame
from mscts.codec.packets import Codec, CodecError, Direction, Packet, State, undecodable_frame
from mscts.transcript import Transcript

_READ_SIZE = 65_536
"""The most bytes one read of the background reader takes from the socket."""

_CLOSE_TIMEOUT_S = 1.0
"""How long close() waits for the socket to finish closing before aborting it."""

_STATE_BY_INTENT: Mapping[int, State] = {1: State.STATUS, 2: State.LOGIN, 3: State.LOGIN}
"""Where the handshake `intention` leads: 1 = status, 2 = login, 3 = transfer (a login)."""

_STATE_AFTER_SENDING: Mapping[tuple[State, str], State] = {
    (State.LOGIN, "minecraft:login_acknowledged"): State.CONFIGURATION,
    (State.CONFIGURATION, "minecraft:finish_configuration"): State.PLAY,
    (State.PLAY, "minecraft:configuration_acknowledged"): State.CONFIGURATION,
}
"""The acks after which what the Connection *sends* is in a new State."""

_STATE_AFTER_RECEIVING: Mapping[tuple[State, str], State] = {
    (State.LOGIN, "minecraft:login_finished"): State.CONFIGURATION,
    (State.CONFIGURATION, "minecraft:finish_configuration"): State.PLAY,
    (State.PLAY, "minecraft:start_configuration"): State.CONFIGURATION,
}
"""The clientbound packets after which what the Connection *receives* is in a new State.

The vanilla client's terminal packets (their `isTerminal()` is true, 26.3 javap): it
decodes every later frame in the new State, whether or not it has acked yet.
"""


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
    """A frame the background reader took, and when the read that completed it returned.

    If the frame could not be decoded, `packet` records it (its `decode_error` set) and
    `error` is what `recv` raises once it has recorded it.
    """

    t_ns: int
    packet: Packet
    error: Exception | None = None


@dataclass(frozen=True, slots=True)
class _End:
    """The background reader stopped, or the Connection closed: `recv` raises `error`."""

    error: Exception


class Connection:
    """One TCP connection to a server. It owns the framing, compression and State.

    Both directions start in handshake, and switch as the vanilla client switches them.
    Sending an `intention` moves both (to status or login, by its intent). After that,
    what it receives switches as each terminal packet arrives (`login_finished` to
    configuration, `finish_configuration` to play, `start_configuration` back to
    configuration), so the very next frame is decoded in the new State; what it sends
    switches once the matching ack has been sent (`login_acknowledged`,
    `finish_configuration`, `configuration_acknowledged`). A `login_compression` that
    arrives sets the compression threshold both ways from the next frame (negative: off).

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
        self._state = State.HANDSHAKE  # what send encodes in
        self._receiving = State.HANDSHAKE  # what the reader decodes in
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
        """The State `send` encodes in: what the Connection sends is in this State."""
        return self._state

    async def send(self, name: str, /, **fields: object) -> None:
        """Encode serverbound packet `name` with `fields` in the current State, and send it.

        It returns once the write has drained (the socket buffer is below its high-water
        mark), and only then records the Packet, stamped immediately before the write,
        and moves the State on. Cancelled while draining, it still records the Packet
        and moves the State on, since the frame is queued and will go out.

        Raises:
            CodecError: The packet is unknown here, or `fields` do not fit its schema.
            ProtocolError: It is an intention with an unknown intent.
            ConnectionClosedError: The Connection is closed, or the connection was lost
                (before the write, or while draining it).

            In each case nothing is recorded, and the State stays.
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
        if packet.name == "minecraft:intention":
            self._receiving = state_after  # the server's answer may arrive while draining
        try:
            await self._writer.drain()
        except ConnectionError as exc:
            msg = "the connection was lost"
            raise ConnectionClosedError(msg) from exc
        except asyncio.CancelledError:
            self._sent(packet, t_ns=t_ns, state_after=state_after)  # the frame is queued
            raise
        self._sent(packet, t_ns=t_ns, state_after=state_after)

    def _sent(self, packet: Packet, *, t_ns: int, state_after: State) -> None:
        self._transcript.record(self._bot, packet, t_ns=t_ns)
        self._state = state_after

    async def recv(self, *, timeout_s: float) -> Packet:
        """Take the next clientbound Packet the background reader decoded, and record it.

        Raises:
            TimeoutError: No complete frame arrived within `timeout_s` seconds. The
                Connection stays usable.
            CodecError: The frame is corrupt, or its packet is unknown or does not fit
                its schema exactly. The frame is recorded first (a Packet with its bytes
                and `decode_error`), and the reader has stopped, as vanilla's client
                disconnects.
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
        if item.error is not None:
            self._end = _End(item.error)
            raise item.error
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
                while (arrival := self._next_arrival(t_ns)) is not None:
                    self._arrivals.put_nowait(arrival)
                    if arrival.error is not None:
                        return  # like vanilla's client, which disconnects on a bad frame
        except Exception as exc:  # noqa: BLE001 - not swallowed: recv raises it
            # Whatever else stopped the reader (the server, or a harness bug) is raised
            # by recv, rather than lost in a task nobody awaits.
            self._arrivals.put_nowait(_End(exc))

    def _next_arrival(self, t_ns: int) -> _Arrival | None:
        """Take and decode the next complete frame, or None if there is none yet.

        A frame that cannot be decoded still arrives: as the Packet that records it.
        """
        state = self._receiving
        try:
            frame = self._frames.next_frame()
        except FrameError as exc:
            error = CodecError(f"{state} {Direction.CLIENTBOUND} frame: {exc}")
            error.__cause__ = exc
            packet = undecodable_frame(state, Direction.CLIENTBOUND, exc.raw, str(error))
            return _Arrival(t_ns=t_ns, packet=packet, error=error)
        if frame is None:
            return None
        try:
            packet = self._codec.decode(state, Direction.CLIENTBOUND, frame)
        except CodecError as exc:
            packet = self._codec.undecodable(state, Direction.CLIENTBOUND, frame, str(exc))
            return _Arrival(t_ns=t_ns, packet=packet, error=exc)
        self._received(packet)
        return _Arrival(t_ns=t_ns, packet=packet)

    def _received(self, packet: Packet) -> None:
        """Apply what `packet` changes for every later frame: compression, or the State."""
        if packet.state is State.LOGIN and packet.name == "minecraft:login_compression":
            threshold = (packet.fields or {}).get("threshold")
            if isinstance(threshold, int):
                self._frames.compression_threshold = threshold
        self._receiving = _STATE_AFTER_RECEIVING.get((packet.state, packet.name), packet.state)

    def _end_of_stream(self) -> _End:
        if self._frames.buffered:
            msg = (
                "the server closed the connection mid-frame, "
                f"{self._frames.buffered} byte(s) into it"
            )
        else:
            msg = "the server closed the connection"
        return _End(ConnectionClosedError(msg))

    def _check_open(self) -> None:
        if self._closed:
            msg = "the connection is closed"
            raise ConnectionClosedError(msg)


def _state_after(packet: Packet) -> State:
    """Return the State a connection sends in once it has sent `packet`.

    Raises:
        ProtocolError: `packet` is an intention with an unknown intent.
    """
    if packet.state is State.HANDSHAKE and packet.name == "minecraft:intention":
        intent = (packet.fields or {}).get("intent")
        if not isinstance(intent, int) or intent not in _STATE_BY_INTENT:
            msg = f"unknown intent {intent!r} (1 = status, 2 = login, 3 = transfer)"
            raise ProtocolError(msg)
        return _STATE_BY_INTENT[intent]
    return _STATE_AFTER_SENDING.get((packet.state, packet.name), packet.state)
