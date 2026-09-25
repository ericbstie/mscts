"""Length-prefixed frames and the login-compression envelope."""

import zlib

from mscts.codec.wire import Writer


def encode_frame(data: bytes, *, compression_threshold: int | None) -> bytes:
    """Wrap `data` in a protocol frame.

    With no compression threshold, a frame is `VarInt length` followed by
    `data` itself.

    With a threshold set, a frame is
    `VarInt length ‖ VarInt data-length ‖ payload`. `payload` is `data`
    zlib-compressed, with `data-length` set to `len(data)`, unless `data` is
    shorter than the threshold, in which case `data-length` is 0 and
    `payload` is `data` unmodified.
    """
    if compression_threshold is None:
        return Writer().var_int(len(data)).to_bytes() + data
    if len(data) >= compression_threshold:
        inner = Writer().var_int(len(data)).to_bytes() + zlib.compress(data)
    else:
        inner = Writer().var_int(0).to_bytes() + data
    return Writer().var_int(len(inner)).to_bytes() + inner
