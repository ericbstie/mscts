"""Length-prefixed frames and the login-compression envelope."""

import zlib

from mscts.codec.wire import Reader, WireError, Writer

_SEGMENT = 0x7F
_CONTINUE = 0x80
_FRAME_LENGTH_MAX_BYTES = 3
_FRAME_LENGTH_MAX_VALUE = 2_097_151

MAX_DATA_LENGTH = 8_388_608
"""The most (uncompressed) data one frame may carry once compression is on.

Vanilla's `CompressionEncoder` and `CompressionDecoder.MAXIMUM_UNCOMPRESSED_LENGTH`.
"""


def _in_effect(compression_threshold: int | None) -> int | None:
    """The threshold that applies, or None if frames are uncompressed.

    None (never set) and a negative threshold both mean uncompressed, as in vanilla's
    `Connection.setupCompression`, which removes the compression handlers for a
    negative threshold.
    """
    if compression_threshold is None or compression_threshold < 0:
        return None
    return compression_threshold


def encode_frame(data: bytes, *, compression_threshold: int | None) -> bytes:
    """Wrap `data` in a protocol frame.

    Uncompressed (no threshold, or a negative one), a frame is `VarInt length`
    followed by `data` itself.

    With a threshold of 0 or more, a frame is
    `VarInt length ‖ VarInt data-length ‖ payload`. `payload` is `data`
    zlib-compressed, with `data-length` set to `len(data)`, unless `data` is
    shorter than the threshold, in which case `data-length` is 0 and
    `payload` is `data` unmodified.

    Raises:
        WireError: `data` is empty (every frame holds at least a packet id), `data` is
            over 8 388 608 bytes with compression on, or the frame length would not
            fit in 3 VarInt bytes (2 097 151): the limits vanilla's encoders enforce.
    """
    if not data:
        msg = "a frame needs at least one byte of data (a packet id)"
        raise WireError(msg)
    threshold = _in_effect(compression_threshold)
    if threshold is None:
        return _length_prefixed(data)
    if len(data) > MAX_DATA_LENGTH:
        msg = f"data length {len(data)} exceeds max {MAX_DATA_LENGTH}"
        raise WireError(msg)
    if len(data) >= threshold:
        inner = Writer().var_int(len(data)).to_bytes() + zlib.compress(data)
    else:
        inner = Writer().var_int(0).to_bytes() + data
    return _length_prefixed(inner)


def _length_prefixed(body: bytes) -> bytes:
    if len(body) > _FRAME_LENGTH_MAX_VALUE:
        msg = f"frame length {len(body)} exceeds max {_FRAME_LENGTH_MAX_VALUE}"
        raise WireError(msg)
    return Writer().var_int(len(body)).to_bytes() + body


def _try_read_frame_length(buffer: bytearray) -> tuple[int, int] | None:
    """Try to read the frame-length VarInt prefix from the front of `buffer`.

    Returns `(value, bytes_consumed)`, or None if `buffer` does not yet hold a
    complete VarInt. Raises WireError if the VarInt is more than 3 bytes or is 0,
    the rules vanilla's `Varint21FrameDecoder` applies ("length wider than 21-bit",
    "Frame length cannot be zero"). Three bytes hold at most 2 097 151, so there is
    no separate upper bound.
    """
    result = 0
    for index in range(_FRAME_LENGTH_MAX_BYTES):
        if index >= len(buffer):
            return None
        byte = buffer[index]
        result |= (byte & _SEGMENT) << (7 * index)
        if not byte & _CONTINUE:
            if result == 0:
                msg = "frame length cannot be zero"
                raise WireError(msg)
            return result, index + 1
    msg = "frame length VarInt longer than 3 bytes"
    raise WireError(msg)


class FrameDecoder:
    """Reassembles complete frames from a byte stream, decompressing as needed.

    `compression_threshold` is a plain attribute, settable at any time, since
    a connection switches from uncompressed to compressed framing mid-stream
    when `login_compression` arrives. None or a negative value means uncompressed.
    """

    def __init__(self, *, compression_threshold: int | None = None) -> None:
        """Start with an empty buffer and the given compression threshold."""
        self._buffer = bytearray()
        self.compression_threshold = compression_threshold

    def extend(self, chunk: bytes) -> None:
        """Add `chunk` to the buffer without taking any frame out."""
        self._buffer.extend(chunk)

    def next_frame(self) -> bytes | None:
        """Take the next complete frame out of the buffer and return its `data`.

        Returns None if the buffer does not hold a complete frame yet. Taking frames
        one at a time lets a new `compression_threshold` apply from the very next
        frame, and lets the frames before a corrupt one through.

        Raises:
            WireError: The next frame is corrupt. A bad frame length stays in the
                buffer, so every later call raises too.
        """
        prefix = _try_read_frame_length(self._buffer)
        if prefix is None:
            return None
        frame_length, prefix_length = prefix
        end = prefix_length + frame_length
        if end > len(self._buffer):
            return None
        body = bytes(self._buffer[prefix_length:end])
        del self._buffer[:end]
        return self._decode_body(body)

    @property
    def buffered(self) -> int:
        """The number of bytes held that have not been taken out as frames."""
        return len(self._buffer)

    def _decode_body(self, body: bytes) -> bytes:
        if _in_effect(self.compression_threshold) is None:
            return body
        reader = Reader(body)
        data_length = reader.var_int()
        payload = body[len(body) - reader.remaining :]
        if data_length == 0:
            return payload
        # A data-length below the threshold is accepted, as vanilla's client does.
        if not 0 < data_length <= MAX_DATA_LENGTH:
            msg = f"declared data-length {data_length} is not in 1..{MAX_DATA_LENGTH}"
            raise WireError(msg)
        return _inflate(payload, data_length)


def _inflate(payload: bytes, data_length: int) -> bytes:
    """Inflate `payload`, one complete zlib stream of exactly `data_length` bytes.

    Inflates at most one byte more than declared, so a stream that claims a little and
    inflates to a lot costs no more than the claim. Bytes after the end of the stream
    are ignored, as vanilla's `CompressionDecoder` ignores them.
    """
    inflater = zlib.decompressobj()
    try:
        data = inflater.decompress(payload, data_length + 1)
    except zlib.error as exc:
        msg = "frame payload is not valid zlib data"
        raise WireError(msg) from exc
    if len(data) > data_length:
        msg = f"declared data-length {data_length}, but it inflates to more"
        raise WireError(msg)
    if not inflater.eof:
        msg = "frame payload is a truncated zlib stream"
        raise WireError(msg)
    if len(data) < data_length:
        msg = f"declared data-length {data_length}, but it inflates to {len(data)}"
        raise WireError(msg)
    return data
