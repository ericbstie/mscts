"""Length-prefixed frames and the login-compression envelope."""

import zlib

from mscts.codec.wire import Reader, WireError, Writer

_SEGMENT = 0x7F
_CONTINUE = 0x80
_FRAME_LENGTH_MAX_BYTES = 3
_FRAME_LENGTH_MAX_VALUE = 2_097_151


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
    """
    threshold = _in_effect(compression_threshold)
    if threshold is None:
        return Writer().var_int(len(data)).to_bytes() + data
    if len(data) >= threshold:
        inner = Writer().var_int(len(data)).to_bytes() + zlib.compress(data)
    else:
        inner = Writer().var_int(0).to_bytes() + data
    return Writer().var_int(len(inner)).to_bytes() + inner


def _try_read_frame_length(buffer: bytearray) -> tuple[int, int] | None:
    """Try to read the frame-length VarInt prefix from the front of `buffer`.

    Returns `(value, bytes_consumed)`, or None if `buffer` does not yet hold a
    complete VarInt. Raises WireError if the VarInt is more than 3 bytes, or
    decodes to a value over 2 097 151 — the limits a frame length must obey.
    """
    result = 0
    for index in range(_FRAME_LENGTH_MAX_BYTES):
        if index >= len(buffer):
            return None
        byte = buffer[index]
        result |= (byte & _SEGMENT) << (7 * index)
        if not byte & _CONTINUE:
            if result > _FRAME_LENGTH_MAX_VALUE:
                msg = f"frame length {result} exceeds max {_FRAME_LENGTH_MAX_VALUE}"
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
        try:
            decompressed = zlib.decompress(payload)
        except zlib.error as exc:
            msg = "frame payload is not valid zlib data"
            raise WireError(msg) from exc
        if len(decompressed) != data_length:
            msg = (
                f"declared data-length {data_length} does not match "
                f"decompressed length {len(decompressed)}"
            )
            raise WireError(msg)
        return decompressed
