import zlib

import pytest

from mscts.codec.framing import FrameDecoder, encode_frame
from mscts.codec.wire import WireError, Writer


def take_all(decoder: FrameDecoder, chunk: bytes) -> list[bytes]:
    """Add `chunk`, then take every complete frame, one at a time."""
    decoder.extend(chunk)
    frames = []
    while (frame := decoder.next_frame()) is not None:
        frames.append(frame)
    return frames


def test_frame_decoder_has_no_batch_feed() -> None:
    # Audit MD4: `feed` decoded every frame of a chunk with the threshold in effect when
    # it was called, so the frame right after login_compression was silently misdecoded.
    # Frames are taken one at a time instead, so a new threshold applies to the next one.
    assert not hasattr(FrameDecoder, "feed")


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
    assert take_all(decoder, frame) == [b"hello"]


def test_frame_decoder_returns_multiple_frames_from_one_chunk() -> None:
    decoder = FrameDecoder()
    chunk = encode_frame(b"first", compression_threshold=None) + encode_frame(
        b"second", compression_threshold=None
    )
    assert take_all(decoder, chunk) == [b"first", b"second"]


def test_frame_decoder_reassembles_a_frame_fed_byte_by_byte() -> None:
    decoder = FrameDecoder()
    frame = encode_frame(b"hello", compression_threshold=None)
    collected = []
    for i in range(len(frame)):
        collected.extend(take_all(decoder, frame[i : i + 1]))
    assert collected == [b"hello"]


def test_frame_decoder_buffers_a_partial_frame_across_calls() -> None:
    decoder = FrameDecoder()
    frame = encode_frame(b"hello", compression_threshold=None)
    split = len(frame) - 1
    assert take_all(decoder, frame[:split]) == []
    assert take_all(decoder, frame[split:]) == [b"hello"]


def test_frame_decoder_passes_through_data_below_threshold() -> None:
    decoder = FrameDecoder(compression_threshold=10)
    frame = encode_frame(b"hi", compression_threshold=10)
    assert take_all(decoder, frame) == [b"hi"]


def test_frame_decoder_decompresses_data_at_or_above_threshold() -> None:
    decoder = FrameDecoder(compression_threshold=100)
    data = b"a" * 300
    frame = encode_frame(data, compression_threshold=100)
    assert take_all(decoder, frame) == [data]


def test_frame_decoder_compression_threshold_is_settable_after_construction() -> None:
    decoder = FrameDecoder()  # starts uncompressed
    first = encode_frame(b"pre-compression", compression_threshold=None)
    assert take_all(decoder, first) == [b"pre-compression"]

    # login_compression arrives mid-connection.
    decoder.compression_threshold = 50
    data = b"b" * 200
    second = encode_frame(data, compression_threshold=50)
    assert take_all(decoder, second) == [data]


def test_frame_decoder_accepts_frame_length_at_the_three_byte_boundary() -> None:
    decoder = FrameDecoder()
    # VarInt 2097151 (0x1FFFFF), the largest value a 3-byte VarInt can hold.
    # No body follows yet, so this must wait rather than raise.
    assert take_all(decoder, bytes.fromhex("ffff7f")) == []


def test_frame_decoder_raises_when_frame_length_is_more_than_three_bytes() -> None:
    decoder = FrameDecoder()
    # A non-minimal 4-byte encoding of 0: continuation bits all set until the
    # 4th byte, one more than the frame-length prefix is allowed to use.
    with pytest.raises(WireError):
        take_all(decoder, bytes.fromhex("80808000"))


def test_frame_decoder_raises_when_declared_data_length_mismatches() -> None:
    decoder = FrameDecoder(compression_threshold=1)
    payload = zlib.compress(b"hello")
    # Falsely declare a decompressed length of 999 instead of 5.
    inner = Writer().var_int(999).to_bytes() + payload
    frame = Writer().var_int(len(inner)).to_bytes() + inner
    with pytest.raises(WireError):
        take_all(decoder, frame)


def test_frame_decoder_raises_on_corrupt_compressed_payload() -> None:
    decoder = FrameDecoder(compression_threshold=1)
    inner = Writer().var_int(5).to_bytes() + b"not zlib data at all"
    frame = Writer().var_int(len(inner)).to_bytes() + inner
    with pytest.raises(WireError):
        take_all(decoder, frame)


def test_next_frame_returns_none_until_a_frame_is_complete() -> None:
    decoder = FrameDecoder()
    assert decoder.next_frame() is None
    frame = encode_frame(b"hello", compression_threshold=None)
    decoder.extend(frame[:-1])
    assert decoder.next_frame() is None
    decoder.extend(frame[-1:])
    assert decoder.next_frame() == b"hello"
    assert decoder.next_frame() is None


def test_next_frame_takes_one_frame_at_a_time_in_order() -> None:
    decoder = FrameDecoder()
    decoder.extend(
        encode_frame(b"first", compression_threshold=None)
        + encode_frame(b"", compression_threshold=None)
        + encode_frame(b"third", compression_threshold=None)
    )
    assert decoder.next_frame() == b"first"
    assert decoder.next_frame() == b""
    assert decoder.next_frame() == b"third"
    assert decoder.next_frame() is None


def test_buffered_counts_the_bytes_not_yet_taken_as_frames() -> None:
    decoder = FrameDecoder()
    assert decoder.buffered == 0
    first = encode_frame(b"first", compression_threshold=None)
    partial = encode_frame(b"second", compression_threshold=None)[:3]
    decoder.extend(first + partial)
    assert decoder.buffered == len(first) + len(partial)
    decoder.next_frame()
    assert decoder.buffered == len(partial)


def test_next_frame_returns_the_frames_before_a_corrupt_one_then_keeps_raising() -> None:
    decoder = FrameDecoder()
    corrupt = bytes.fromhex("80808000")  # a frame length longer than 3 bytes
    decoder.extend(encode_frame(b"good", compression_threshold=None) + corrupt)
    assert decoder.next_frame() == b"good"
    for _ in range(2):
        with pytest.raises(WireError, match="longer than 3 bytes"):
            decoder.next_frame()
    assert decoder.buffered == len(corrupt)


def test_a_threshold_set_between_frames_applies_to_the_next_frame_of_the_same_chunk() -> None:
    # login_compression and the first compressed frame can arrive in one read.
    decoder = FrameDecoder()
    data = b"c" * 64
    decoder.extend(
        encode_frame(b"login_compression", compression_threshold=None)
        + encode_frame(data, compression_threshold=16)
    )
    assert decoder.next_frame() == b"login_compression"
    decoder.compression_threshold = 16
    assert decoder.next_frame() == data
