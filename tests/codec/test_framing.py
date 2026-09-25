import zlib

import pytest

from mscts.codec.framing import FrameDecoder, encode_frame
from mscts.codec.wire import WireError, Writer


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


def test_frame_decoder_returns_one_frame_from_a_single_chunk() -> None:
    decoder = FrameDecoder()
    frame = encode_frame(b"hello", compression_threshold=None)
    assert decoder.feed(frame) == [b"hello"]


def test_frame_decoder_returns_multiple_frames_from_one_chunk() -> None:
    decoder = FrameDecoder()
    chunk = encode_frame(b"first", compression_threshold=None) + encode_frame(
        b"second", compression_threshold=None
    )
    assert decoder.feed(chunk) == [b"first", b"second"]


def test_frame_decoder_reassembles_a_frame_fed_byte_by_byte() -> None:
    decoder = FrameDecoder()
    frame = encode_frame(b"hello", compression_threshold=None)
    collected = []
    for i in range(len(frame)):
        collected.extend(decoder.feed(frame[i : i + 1]))
    assert collected == [b"hello"]


def test_frame_decoder_buffers_a_partial_frame_across_calls() -> None:
    decoder = FrameDecoder()
    frame = encode_frame(b"hello", compression_threshold=None)
    split = len(frame) - 1
    assert decoder.feed(frame[:split]) == []
    assert decoder.feed(frame[split:]) == [b"hello"]


def test_frame_decoder_passes_through_data_below_threshold() -> None:
    decoder = FrameDecoder(compression_threshold=10)
    frame = encode_frame(b"hi", compression_threshold=10)
    assert decoder.feed(frame) == [b"hi"]


def test_frame_decoder_decompresses_data_at_or_above_threshold() -> None:
    decoder = FrameDecoder(compression_threshold=100)
    data = b"a" * 300
    frame = encode_frame(data, compression_threshold=100)
    assert decoder.feed(frame) == [data]


def test_frame_decoder_compression_threshold_is_settable_after_construction() -> None:
    decoder = FrameDecoder()  # starts uncompressed
    first = encode_frame(b"pre-compression", compression_threshold=None)
    assert decoder.feed(first) == [b"pre-compression"]

    # login_compression arrives mid-connection.
    decoder.compression_threshold = 50
    data = b"b" * 200
    second = encode_frame(data, compression_threshold=50)
    assert decoder.feed(second) == [data]


def test_frame_decoder_accepts_frame_length_at_the_three_byte_boundary() -> None:
    decoder = FrameDecoder()
    # VarInt 2097151 (0x1FFFFF), the largest value a 3-byte VarInt can hold.
    # No body follows yet, so this must wait rather than raise.
    assert decoder.feed(bytes.fromhex("ffff7f")) == []


def test_frame_decoder_raises_when_frame_length_is_more_than_three_bytes() -> None:
    decoder = FrameDecoder()
    # A non-minimal 4-byte encoding of 0: continuation bits all set until the
    # 4th byte, one more than the frame-length prefix is allowed to use.
    with pytest.raises(WireError):
        decoder.feed(bytes.fromhex("80808000"))


def test_frame_decoder_raises_when_declared_data_length_mismatches() -> None:
    decoder = FrameDecoder(compression_threshold=1)
    payload = zlib.compress(b"hello")
    # Falsely declare a decompressed length of 999 instead of 5.
    inner = Writer().var_int(999).to_bytes() + payload
    frame = Writer().var_int(len(inner)).to_bytes() + inner
    with pytest.raises(WireError):
        decoder.feed(frame)


def test_frame_decoder_raises_on_corrupt_compressed_payload() -> None:
    decoder = FrameDecoder(compression_threshold=1)
    inner = Writer().var_int(5).to_bytes() + b"not zlib data at all"
    frame = Writer().var_int(len(inner)).to_bytes() + inner
    with pytest.raises(WireError):
        decoder.feed(frame)
