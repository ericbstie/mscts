import zlib

from mscts.codec.framing import encode_frame
from mscts.codec.wire import Writer


def test_encode_frame_uncompressed_is_length_prefixed_data() -> None:
    data = b"hello"
    assert encode_frame(data, compression_threshold=None) == bytes([5]) + data


def test_encode_frame_uncompressed_uses_var_int_length() -> None:
    data = b"x" * 200  # length 200 needs a 2-byte VarInt
    expected = Writer().var_int(len(data)).to_bytes() + data
    assert encode_frame(data, compression_threshold=None) == expected


def test_encode_frame_below_threshold_is_data_length_zero_and_raw_data() -> None:
    data = b"hi"
    threshold = 5
    inner = bytes([0]) + data  # VarInt data-length 0, then raw data
    expected = Writer().var_int(len(inner)).to_bytes() + inner
    assert encode_frame(data, compression_threshold=threshold) == expected


def test_encode_frame_at_threshold_is_compressed() -> None:
    # len(data) >= threshold, so this compresses even at the boundary.
    data = b"a" * 10
    threshold = 10
    payload = zlib.compress(data)
    inner = Writer().var_int(len(data)).to_bytes() + payload
    expected = Writer().var_int(len(inner)).to_bytes() + inner
    assert encode_frame(data, compression_threshold=threshold) == expected


def test_encode_frame_above_threshold_is_compressed() -> None:
    data = b"a" * 300
    threshold = 100
    payload = zlib.compress(data)
    inner = Writer().var_int(len(data)).to_bytes() + payload
    expected = Writer().var_int(len(inner)).to_bytes() + inner
    assert encode_frame(data, compression_threshold=threshold) == expected
    # Sanity: this really is compressed, i.e. smaller than the raw data.
    assert len(payload) < len(data)
