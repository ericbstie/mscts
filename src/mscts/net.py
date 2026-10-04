"""Reaching a server over the network: Endpoints and Connections."""

import asyncio
import contextlib
import fcntl
import os
import socket
import sys
import termios
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Self, override

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
    """The Connection is closed: the server closed it, it was lost, or `close()` was called."""


class ProtocolError(Exception):
    """A packet that breaks the protocol's sequence, e.g. an intention with an unknown intent."""


type Answer = Callable[[Connection, Packet], Awaitable[None]]
"""What a Connection's reader does with each Packet as it arrives (e.g. a Bot's replies)."""


@dataclass(frozen=True, slots=True)
class _Arrival:
    """A frame the background reader took, and when the read that completed it returned.

    If the frame could not be decoded, `packet` records it (its `decode_error` set) and
    `error` is what `recv` raises once it has recorded it.
    """

    t_ns: int
    packet: Packet
    error: Exception | None = None


class _Stream(asyncio.StreamReader):
    """A StreamReader that still yields what arrived when the connection is lost.

    asyncio's raises the loss (any OSError: a reset, a TCP timeout, or a failed write:
    EPIPE) on the next read, ahead of the bytes it already holds, so a server's last
    frames would be lost (#291). This one ends the stream after those bytes instead, and
    keeps the loss in `lost`.

    When a write fails, asyncio also stops reading and closes the socket, dropping what
    the socket still holds. It tells this reader first, while the socket is open, so this
    one takes those bytes before it ends the stream.

    A loss after the stream has ended (the server closed it, then a write failed) is not
    recorded: the server closed the connection, whatever was written after.
    """

    lost: OSError | None = None
    _socket: socket.socket | None = None
    _ended = False

    @override
    def feed_eof(self) -> None:
        """End the stream, as asyncio does, and remember it has ended."""
        self._ended = True
        super().feed_eof()

    @override
    def set_transport(self, transport: asyncio.BaseTransport) -> None:
        """Keep the transport's socket, to take what it still holds when the connection is lost."""
        super().set_transport(transport)
        self._socket = transport.get_extra_info("socket")

    @override
    def set_exception(self, exc: Exception) -> None:
        """Record a lost connection and end the stream; set any other error as asyncio does."""
        if not isinstance(exc, OSError):
            super().set_exception(exc)
            return
        if self._ended:
            return
        self.lost = exc
        self._take_what_the_socket_holds()
        self.feed_eof()

    def _take_what_the_socket_holds(self) -> None:
        """Feed what the socket still holds, to its end, without waiting for more."""
        if self._socket is None or self._socket.fileno() < 0:
            return
        while True:
            try:
                data = os.read(self._socket.fileno(), _READ_SIZE)
            except OSError:  # nothing more yet (it does not block), or the reset
                return
            if not data:  # the server's close
                return
            self.feed_data(data)


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
    it for `recv`, so a frame's time is when it arrived, not when it was taken. The
    frames one read completed are stamped a nanosecond apart, in order, so a Mark can
    fall between any two of them.

    Every Packet it sends or receives is recorded to its Transcript as an Event of
    its Bot:

    - A sent Packet is stamped immediately before its frame is written to the
      socket, and it is recorded as decoded from the exact bytes written.
    - A received Packet is recorded when `recv` returns it, with its arrival stamp.
      So the Transcript holds the frames the Bot took, whatever the TCP segmentation,
      and frames that arrived together keep the time they arrived (to the nanosecond
      that orders them), however late they are taken.
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
        self._answer: Answer | None = None
        self._last_arrival_ns: int | None = None
        self._stamped_bytes = 0  # every byte the reader has read, each stamped as it was
        self._reading = asyncio.get_running_loop().create_task(
            self._read_forever(), name=f"mscts Connection reader ({bot})"
        )

    @classmethod
    async def open(
        cls,
        endpoint: Endpoint,
        codec: Codec,
        *,
        bot: str,
        transcript: Transcript,
        answer: Answer | None = None,
    ) -> Self:
        """Connect to `endpoint`, in the handshake State, recording as `bot`.

        asyncio turns Nagle's algorithm off (TCP_NODELAY), so small frames are
        written at once rather than held back for coalescing.

        `answer`, if given, is awaited by the background reader for each Packet it
        decodes, in wire order, as the packet arrives, before the next frame is taken;
        the vanilla client answers keep-alives, teleports and acks the same way, whether
        or not anyone is reading. The Packet is queued for `recv` once its answer has
        returned, so whoever takes it knows the answer was sent. If the connection is
        lost, the answer's send fails and the reader reads on to the end of the stream:
        every frame that arrived before the loss is still taken.
        Anything else an answer raises stops the reader, and `recv` raises it right
        after the Packet it was answering.

        Raises:
            OSError: The connection failed, e.g. ConnectionRefusedError.
        """
        # asyncio.open_connection, with a reader that keeps what arrived before a loss.
        loop = asyncio.get_running_loop()
        reader = _Stream(loop=loop)
        protocol = asyncio.StreamReaderProtocol(reader, loop=loop)
        transport, _ = await loop.create_connection(lambda: protocol, endpoint.host, endpoint.port)
        writer = asyncio.StreamWriter(transport, protocol, reader, loop)
        connection = cls(reader, writer, codec, bot=bot, transcript=transcript)
        connection._answer = answer  # nothing has awaited since: the reader has not run yet
        return connection

    @property
    def state(self) -> State:
        """The State `send` encodes in: what the Connection sends is in this State."""
        return self._state

    @property
    def transcript(self) -> Transcript:
        """The Transcript this Connection records to."""
        return self._transcript

    @property
    def last_arrival_ns(self) -> int | None:
        """When the Packet `recv` last returned arrived, as the Transcript stamps it.

        None until `recv` has returned a Packet. It is the arrival time, not the time
        `recv` took the Packet, so it holds when the caller was busy meanwhile.
        """
        return self._last_arrival_ns

    async def caught_up(self) -> None:
        """Return once the reader has stamped every byte that had reached the socket on entry.

        The backlog is what waits then in the kernel's receive buffer (FIONREAD, on Linux
        and macOS) and in the stream's buffer. So whatever arrived before this was called
        is stamped before any time taken after it returns, however busy the event loop
        was. Bytes that arrive meanwhile are not waited for, so a stream with no gaps
        ends it too. It also returns once the reader has ended.
        """
        # asyncio has no public view of what its StreamReader holds (CPython: `_buffer`).
        held = len(getattr(self._reader, "_buffer", b""))
        target = self._stamped_bytes + held + _unread(self._writer)
        while True:
            if self._reading.done() or self._stamped_bytes >= target:
                return
            await asyncio.sleep(0)  # a turn of the loop: the transport reads, the reader stamps

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

    async def send_all(self, packets: Sequence[tuple[str, Mapping[str, object]]]) -> None:
        """Send each (name, fields) packet, in order, in one write, then drain as `send` does.

        A burst that the server must read within one tick (a chat spam kick) goes out with
        no gap between its frames in which a tick could fall. Every packet is stamped
        immediately before the write and recorded once it has drained, in order.

        Raises:
            ValueError: `packets` is empty, or a packet would change the State (send that
                one on its own, as the frames after it would need the next State).
            CodecError: A packet is unknown here, or its fields do not fit its schema.
            ConnectionClosedError: As for `send`.

            In each case, but a connection lost while draining, nothing is written or
            recorded.
        """
        if not packets:
            msg = "send_all needs at least one packet"
            raise ValueError(msg)
        self._check_open()
        encoded = []
        for name, fields in packets:
            data = self._codec.encode(self._state, Direction.SERVERBOUND, name, fields)
            packet = self._codec.decode(self._state, Direction.SERVERBOUND, data)
            if _state_after(packet) is not self._state:
                msg = f"{name} changes the State: send it on its own"
                raise ValueError(msg)
            frame = encode_frame(data, compression_threshold=self._frames.compression_threshold)
            encoded.append((packet, frame))
        if self._writer.transport.is_closing():
            msg = "the connection was lost"
            raise ConnectionClosedError(msg)
        t_ns = self._transcript.now_ns()
        self._writer.write(b"".join(frame for _, frame in encoded))
        try:
            await self._writer.drain()
        except ConnectionError as exc:
            msg = "the connection was lost"
            raise ConnectionClosedError(msg) from exc
        except asyncio.CancelledError:
            for packet, _ in encoded:  # the frames are queued
                self._sent(packet, t_ns=t_ns, state_after=self._state)
            raise
        for packet, _ in encoded:
            self._sent(packet, t_ns=t_ns, state_after=self._state)

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
            ConnectionClosedError: The Connection is closed, the server closed it, or
                the connection was lost, e.g. reset (the message says which, and if that
                was mid-frame). It comes after every frame that arrived before it.

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
        self._last_arrival_ns = item.t_ns
        if item.error is not None:
            self._end = _End(item.error)
            raise item.error
        return item.packet

    async def close(self) -> None:
        """Stop the reader and close the connection. Calling it again does nothing.

        A `recv` still waiting raises ConnectionClosedError. If the socket has not
        finished closing within a second (a server that stops reading can hold unsent
        bytes back), it is aborted. Cancelled while it waits, it still closes the socket,
        and raises CancelledError.
        """
        if self._closed:
            return
        self._closed = True
        self._reading.cancel()
        try:
            await asyncio.wait({self._reading})
        finally:
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
                self._stamped_bytes += len(chunk)
                if not chunk:
                    self._arrivals.put_nowait(self._end_of_stream())
                    return
                self._frames.extend(chunk)
                while (arrival := self._next_arrival(t_ns)) is not None:
                    t_ns += 1  # the next frame of this read arrived a nanosecond later
                    failure = await self._answered(arrival)
                    self._arrivals.put_nowait(arrival)
                    if failure is not None:
                        self._arrivals.put_nowait(_End(failure))
                        return
                    if arrival.error is not None:
                        return  # like vanilla's client, which disconnects on a bad frame
        except ConnectionError as exc:  # a plain StreamReader raises the loss (_Stream ends)
            self._arrivals.put_nowait(self._end_of_stream(exc))
        except Exception as exc:  # noqa: BLE001 - not swallowed: recv raises it
            # Whatever else stopped the reader (the server, or a harness bug) is raised
            # by recv, rather than lost in a task nobody awaits.
            self._arrivals.put_nowait(_End(exc))

    async def _answered(self, arrival: _Arrival) -> Exception | None:
        """Run the answer for a decoded arrival; return what it raised, if that must stop us.

        A send that found the connection lost is not a failure: the reader reads on.
        """
        if self._answer is None or arrival.error is not None:
            return None
        try:
            await self._answer(self, arrival.packet)
        except ConnectionClosedError:
            return None
        except Exception as exc:  # noqa: BLE001 - not swallowed: recv raises it
            return exc
        return None

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

    def _end_of_stream(self, lost: OSError | None = None) -> _End:
        if lost is None and isinstance(self._reader, _Stream):
            lost = self._reader.lost
        if lost is None:
            msg = "the server closed the connection"
        elif lost.strerror:  # the system's reason, e.g. "Connection reset by peer"
            msg = f"the connection was lost ({lost.strerror[0].lower()}{lost.strerror[1:]})"
        else:
            msg = "the connection was lost"
        if self._frames.buffered:
            msg += f" mid-frame, {self._frames.buffered} byte(s) into it"
        error = ConnectionClosedError(msg)
        error.__cause__ = lost
        return _End(error)

    def _check_open(self) -> None:
        if self._closed:
            msg = "the connection is closed"
            raise ConnectionClosedError(msg)


def _unread(writer: asyncio.StreamWriter) -> int:
    """How many received bytes wait in the socket's kernel buffer (0 once it is closed)."""
    sock = writer.get_extra_info("socket")
    if sock is None or sock.fileno() < 0:
        return 0
    try:
        answer = fcntl.ioctl(sock.fileno(), termios.FIONREAD, b"\0" * 4)
    except OSError:
        return 0
    return int.from_bytes(answer, sys.byteorder, signed=True)


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
