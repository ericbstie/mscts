import math
import struct
import uuid
from typing import cast

import pytest

from mscts.codec.wire import Reader, WireError, Writer

# Sample table from minecraft.wiki "Java Edition protocol/VarInt and VarLong".
VAR_INT_SAMPLES = [
    (0, "00"),
    (1, "01"),
    (2, "02"),
    (127, "7f"),
    (128, "8001"),
    (255, "ff01"),
    (25565, "ddc701"),
    (2097151, "ffff7f"),
    (2147483647, "ffffffff07"),
    (-1, "ffffffff0f"),
    (-2147483648, "8080808008"),
]


@pytest.mark.parametrize(("value", "encoded"), VAR_INT_SAMPLES)
def test_var_int_encodes_to_wiki_sample(value: int, encoded: str) -> None:
    assert Writer().var_int(value).to_bytes() == bytes.fromhex(encoded)


@pytest.mark.parametrize(("value", "encoded"), VAR_INT_SAMPLES)
def test_var_int_decodes_wiki_sample(value: int, encoded: str) -> None:
    assert Reader(bytes.fromhex(encoded)).var_int() == value


def test_var_int_raises_on_truncated_input() -> None:
    # A continuation byte with nothing after it: the value is incomplete.
    with pytest.raises(WireError):
        Reader(bytes.fromhex("80")).var_int()


def test_var_int_raises_on_empty_input() -> None:
    with pytest.raises(WireError):
        Reader(b"").var_int()


def test_var_int_raises_when_longer_than_five_bytes() -> None:
    # Five continuation bytes followed by a terminator: 6 bytes total.
    with pytest.raises(WireError):
        Reader(bytes.fromhex("8080808080 00".replace(" ", ""))).var_int()


# Sample table from minecraft.wiki "Java Edition protocol/VarInt and VarLong".
VAR_LONG_SAMPLES = [
    (0, "00"),
    (1, "01"),
    (2, "02"),
    (127, "7f"),
    (128, "8001"),
    (255, "ff01"),
    (2147483647, "ffffffff07"),
    (9223372036854775807, "ffffffffffffffff7f"),
    (-1, "ffffffffffffffffff01"),
    (-2147483648, "80808080f8ffffffff01"),
    (-9223372036854775808, "80808080808080808001"),
]


@pytest.mark.parametrize(("value", "encoded"), VAR_LONG_SAMPLES)
def test_var_long_encodes_to_wiki_sample(value: int, encoded: str) -> None:
    assert Writer().var_long(value).to_bytes() == bytes.fromhex(encoded)


@pytest.mark.parametrize(("value", "encoded"), VAR_LONG_SAMPLES)
def test_var_long_decodes_wiki_sample(value: int, encoded: str) -> None:
    assert Reader(bytes.fromhex(encoded)).var_long() == value


def test_var_long_raises_on_truncated_input() -> None:
    with pytest.raises(WireError):
        Reader(bytes.fromhex("80")).var_long()


def test_var_long_raises_on_empty_input() -> None:
    with pytest.raises(WireError):
        Reader(b"").var_long()


def test_var_long_raises_when_longer_than_ten_bytes() -> None:
    # Ten continuation bytes followed by a terminator: 11 bytes total.
    with pytest.raises(WireError):
        Reader(bytes.fromhex("80" * 10 + "00")).var_long()


# Vanilla's VarInt.read / VarLong.read (26.3, javap -c) do `out |= (b & 127) << (n++ * 7)`
# in 32-bit (`ishl`) / 64-bit (`lshl`) arithmetic, so the high bits of the last byte fall
# off: a non-canonical 5th (10th) byte still decodes to an in-range value.
@pytest.mark.parametrize(
    ("encoded", "value"),
    [
        ("ffffffff7f", -1),  # canonical -1 is ffffffff0f
        ("ffffffff1f", -1),
        ("8080808010", 0),  # bit 32 falls off
        ("8080808078", -(2**31)),  # 0x78 << 28: only bit 3 (value 8) is kept, as bit 31
    ],
)
def test_var_int_keeps_only_32_bits_as_vanilla_does(encoded: str, value: int) -> None:
    reader = Reader(bytes.fromhex(encoded))
    assert reader.var_int() == value
    assert reader.remaining == 0


@pytest.mark.parametrize(
    ("encoded", "value"),
    [
        ("ff" * 9 + "7f", -1),  # canonical -1 is ff*9 01
        ("80" * 9 + "02", 0),  # bit 64 falls off
        ("80" * 9 + "03", -(2**63)),
    ],
)
def test_var_long_keeps_only_64_bits_as_vanilla_does(encoded: str, value: int) -> None:
    reader = Reader(bytes.fromhex(encoded))
    assert reader.var_long() == value
    assert reader.remaining == 0


# A VarInt is a signed 32-bit integer and a VarLong a signed 64-bit one;
# anything outside must not be silently wrapped into range.
@pytest.mark.parametrize("value", [2**31, -(2**31) - 1])
def test_var_int_writer_raises_when_out_of_range(value: int) -> None:
    with pytest.raises(WireError, match="out of range"):
        Writer().var_int(value)


@pytest.mark.parametrize("value", [2**63, -(2**63) - 1])
def test_var_long_writer_raises_when_out_of_range(value: int) -> None:
    with pytest.raises(WireError, match="out of range"):
        Writer().var_long(value)


# String: VarInt byte-length prefix ‖ UTF-8 bytes. The length limit `n` counts
# UTF-16 code units (a scalar value above U+FFFF counts as two), and the byte
# length must be <= n * 3. Source: minecraft.wiki
# "Java Edition protocol/Data types", the String row.


def test_string_round_trips_ascii() -> None:
    written = Writer().string("hello", max_length=5).to_bytes()
    assert written == bytes([5]) + b"hello"
    assert Reader(written).string(max_length=5) == "hello"


def test_string_round_trips_multibyte_utf8() -> None:
    # "café": 4 code points / 4 UTF-16 units, but 5 UTF-8 bytes (é is 2 bytes).
    written = Writer().string("café", max_length=4).to_bytes()
    encoded = "café".encode()
    assert written == bytes([len(encoded)]) + encoded
    assert Reader(written).string(max_length=4) == "café"


def test_string_non_bmp_scalar_counts_as_two_code_units() -> None:
    # U+1F600 is one scalar value / one Python character, but two UTF-16
    # code units, and needs 4 UTF-8 bytes.
    emoji = "\U0001f600"
    written = Writer().string(emoji, max_length=2).to_bytes()
    encoded = emoji.encode()
    assert written == bytes([len(encoded)]) + encoded
    assert Reader(written).string(max_length=2) == emoji


def test_string_writer_raises_when_code_units_exceed_max_length() -> None:
    emoji = "\U0001f600"  # 2 UTF-16 code units
    with pytest.raises(WireError):
        Writer().string(emoji, max_length=1)


@pytest.mark.parametrize("text", [chr(0xD800), "a" + chr(0xDFFF) + "b"])
def test_string_writer_raises_on_a_lone_surrogate(text: str) -> None:
    # Audit L1: str.encode raised UnicodeEncodeError, escaping the CodecError contract.
    with pytest.raises(WireError, match="string is not valid Unicode"):
        Writer().string(text, max_length=5)


def test_string_reader_raises_on_a_negative_byte_length() -> None:
    # Audit W7: without the guard, a negative length moves the offset backwards and
    # later fields re-read old bytes. Vanilla: "less than zero! Weird string!".
    data = bytes.fromhex("ffffffff0f") + b"abc"
    with pytest.raises(WireError, match="string byte length -1"):
        Reader(data).string(max_length=5)


def test_string_limit_counts_utf16_code_units_not_characters_or_bytes() -> None:
    # Audit W10: two U+1F600 are 2 characters and 8 UTF-8 bytes (within 3 x 3 = 9), but
    # 4 UTF-16 code units, one over max_length 3.
    two_emoji = chr(0x1F600) * 2
    with pytest.raises(WireError, match="exceeds max length 3 UTF-16 code units"):
        Writer().string(two_emoji, max_length=3)
    data = Writer().string(two_emoji, max_length=4).to_bytes()
    with pytest.raises(WireError, match="exceeds max length 3 UTF-16 code units"):
        Reader(data).string(max_length=3)


def test_string_writer_allows_exactly_max_length() -> None:
    Writer().string("abcde", max_length=5)  # must not raise


def test_string_writer_raises_when_one_over_max_length() -> None:
    with pytest.raises(WireError):
        Writer().string("abcdef", max_length=5)


def test_string_reader_raises_when_declared_length_exceeds_three_times_max() -> None:
    # Declared byte length 4 > max_length(1) * 3 == 3: reject before reading.
    data = bytes([4]) + b"abcd"
    with pytest.raises(WireError):
        Reader(data).string(max_length=1)


def test_string_reader_raises_when_truncated() -> None:
    # Declares 5 bytes but only 2 follow.
    data = bytes([5]) + b"ab"
    with pytest.raises(WireError):
        Reader(data).string(max_length=5)


def test_string_reader_raises_on_invalid_utf8() -> None:
    data = bytes([2]) + b"\xff\xfe"
    with pytest.raises(WireError):
        Reader(data).string(max_length=5)


def test_string_reader_raises_when_decoded_code_units_exceed_max_length() -> None:
    # Byte length 2 <= max_length(1) * 3, but "ab" decodes to 2 code units.
    data = bytes([2]) + b"ab"
    with pytest.raises(WireError):
        Reader(data).string(max_length=1)


# UShort: unsigned 16-bit, big-endian. Source: minecraft.wiki
# "Java Edition protocol/Data types" ("All data sent over the network
# (except for VarInt and VarLong) is big-endian").

USHORT_SAMPLES = [
    (0, "0000"),
    (1, "0001"),
    (256, "0100"),
    (25565, "63dd"),
    (65535, "ffff"),
]


@pytest.mark.parametrize(("value", "encoded"), USHORT_SAMPLES)
def test_ushort_encodes_big_endian(value: int, encoded: str) -> None:
    assert Writer().ushort(value).to_bytes() == bytes.fromhex(encoded)


@pytest.mark.parametrize(("value", "encoded"), USHORT_SAMPLES)
def test_ushort_decodes_big_endian(value: int, encoded: str) -> None:
    assert Reader(bytes.fromhex(encoded)).ushort() == value


def test_ushort_writer_raises_when_negative() -> None:
    with pytest.raises(WireError):
        Writer().ushort(-1)


def test_ushort_writer_raises_when_out_of_range() -> None:
    with pytest.raises(WireError):
        Writer().ushort(65536)


def test_ushort_reader_raises_on_truncated_input() -> None:
    with pytest.raises(WireError):
        Reader(bytes.fromhex("00")).ushort()


# Long: signed 64-bit, big-endian, two's complement.

LONG_SAMPLES = [
    (0, "0000000000000000"),
    (1, "0000000000000001"),
    (-1, "ffffffffffffffff"),
    (9223372036854775807, "7fffffffffffffff"),
    (-9223372036854775808, "8000000000000000"),
]


@pytest.mark.parametrize(("value", "encoded"), LONG_SAMPLES)
def test_long_encodes_big_endian(value: int, encoded: str) -> None:
    assert Writer().long(value).to_bytes() == bytes.fromhex(encoded)


@pytest.mark.parametrize(("value", "encoded"), LONG_SAMPLES)
def test_long_decodes_big_endian(value: int, encoded: str) -> None:
    assert Reader(bytes.fromhex(encoded)).long() == value


def test_long_writer_raises_when_out_of_range() -> None:
    with pytest.raises(WireError):
        Writer().long(9223372036854775808)


def test_long_reader_raises_on_truncated_input() -> None:
    with pytest.raises(WireError):
        Reader(bytes.fromhex("00000000000000")).long()


# Byte, Int: signed 8- and 32-bit, big-endian, two's complement (wiki Data types).

BYTE_SAMPLES = [(0, "00"), (1, "01"), (-1, "ff"), (127, "7f"), (-128, "80")]
INT_SAMPLES = [
    (0, "00000000"),
    (1, "00000001"),
    (-1, "ffffffff"),
    (2147483647, "7fffffff"),
    (-2147483648, "80000000"),
]


@pytest.mark.parametrize(("value", "encoded"), BYTE_SAMPLES)
def test_byte_round_trips(value: int, encoded: str) -> None:
    assert Writer().byte(value).to_bytes() == bytes.fromhex(encoded)
    assert Reader(bytes.fromhex(encoded)).byte() == value


@pytest.mark.parametrize(("value", "encoded"), INT_SAMPLES)
def test_int_round_trips(value: int, encoded: str) -> None:
    assert Writer().int_(value).to_bytes() == bytes.fromhex(encoded)
    assert Reader(bytes.fromhex(encoded)).int_() == value


@pytest.mark.parametrize(
    ("write", "value"),
    [("byte", 128), ("byte", -129), ("int_", 2**31), ("int_", -(2**31) - 1)],
)
def test_byte_and_int_writers_raise_when_out_of_range(write: str, value: int) -> None:
    with pytest.raises(WireError, match="out of range"):
        getattr(Writer(), write)(value)


@pytest.mark.parametrize(("read", "data"), [("byte", ""), ("int_", "000000")])
def test_byte_and_int_readers_raise_on_truncated_input(read: str, data: str) -> None:
    with pytest.raises(WireError, match="truncated"):
        getattr(Reader(bytes.fromhex(data)), read)()


# Float, Double: IEEE 754 binary32 / binary64, big-endian (wiki Data types).

FLOAT_SAMPLES = [(0.0, "00000000"), (-0.0, "80000000"), (1.0, "3f800000"), (-90.5, "c2b50000")]
DOUBLE_SAMPLES = [(0.0, "0000000000000000"), (-0.0, "8000000000000000"), (6.5, "401a000000000000")]


def bits(value: float) -> bytes:
    """`value` as binary64, so -0.0 and 0.0 (equal as floats) compare unequal."""
    return struct.pack(">d", value)


@pytest.mark.parametrize(("value", "encoded"), FLOAT_SAMPLES)
def test_float_round_trips_bit_for_bit(value: float, encoded: str) -> None:
    assert Writer().float_(value).to_bytes() == bytes.fromhex(encoded)
    assert bits(Reader(bytes.fromhex(encoded)).float_()) == bits(value)


@pytest.mark.parametrize(("value", "encoded"), DOUBLE_SAMPLES)
def test_double_round_trips_bit_for_bit(value: float, encoded: str) -> None:
    assert Writer().double(value).to_bytes() == bytes.fromhex(encoded)
    assert bits(Reader(bytes.fromhex(encoded)).double()) == bits(value)


@pytest.mark.parametrize("value", [math.inf, -math.inf])
def test_float_and_double_carry_infinities(value: float) -> None:
    assert Reader(Writer().float_(value).to_bytes()).float_() == value
    assert Reader(Writer().double(value).to_bytes()).double() == value


def test_float_and_double_carry_nan() -> None:
    assert math.isnan(Reader(Writer().float_(math.nan).to_bytes()).float_())
    assert math.isnan(Reader(Writer().double(math.nan).to_bytes()).double())


def test_float_writer_refuses_a_value_binary32_cannot_hold_exactly() -> None:
    # 0.1 would be rounded; the Transcript would then hold a value nobody asked for.
    with pytest.raises(WireError, match=r"0\.1 is not exactly a Float"):
        Writer().float_(0.1)
    with pytest.raises(WireError, match="is not exactly a Float"):
        Writer().float_(1e39)  # beyond binary32's range


@pytest.mark.parametrize("write", ["float_", "double"])
@pytest.mark.parametrize("value", [1, True, "1.0", None])
def test_float_and_double_writers_refuse_a_value_that_is_not_a_float(
    write: str, value: object
) -> None:
    with pytest.raises(WireError, match="expected a float"):
        getattr(Writer(), write)(value)


@pytest.mark.parametrize(("read", "data"), [("float_", "000000"), ("double", "00" * 7)])
def test_float_and_double_readers_raise_on_truncated_input(read: str, data: str) -> None:
    with pytest.raises(WireError, match="truncated"):
        getattr(Reader(bytes.fromhex(data)), read)()


# Raw bytes: a known count, or the rest of the data (a Byte Array whose length is known
# from its context, e.g. the end of the packet).


def test_raw_and_rest_read_bytes_as_they_are() -> None:
    reader = Reader(bytes.fromhex("0102 030405"))
    assert reader.raw(2) == bytes.fromhex("0102")
    assert reader.rest() == bytes.fromhex("030405")
    assert reader.rest() == b""
    assert Writer().raw(b"\x00\xff").to_bytes() == b"\x00\xff"


def test_raw_raises_when_truncated() -> None:
    with pytest.raises(WireError, match="3 byte\\(s\\) truncated"):
        Reader(b"\x01\x02").raw(3)


# Bool: true is 0x01, false is 0x00; any other byte is invalid.


def test_bool_encodes_true_and_false() -> None:
    assert Writer().bool_(value=True).to_bytes() == bytes([0x01])
    assert Writer().bool_(value=False).to_bytes() == bytes([0x00])


def test_bool_decodes_true_and_false() -> None:
    assert Reader(bytes([0x01])).bool_() is True
    assert Reader(bytes([0x00])).bool_() is False


@pytest.mark.parametrize("value", [1, 0, 2, "", None])
def test_bool_writer_raises_unless_given_a_bool(value: object) -> None:
    with pytest.raises(WireError, match="expected a bool"):
        Writer().bool_(value=cast("bool", value))


def test_bool_reader_raises_on_invalid_byte() -> None:
    with pytest.raises(WireError):
        Reader(bytes([0x02])).bool_()


def test_bool_reader_raises_on_truncated_input() -> None:
    with pytest.raises(WireError):
        Reader(b"").bool_()


# UUID: 128-bit, big-endian, i.e. `uuid.UUID.bytes`.

NIL_UUID = uuid.UUID(int=0)
SAMPLE_UUID = uuid.UUID("12345678-1234-5678-1234-567812345678")


@pytest.mark.parametrize("value", [NIL_UUID, SAMPLE_UUID])
def test_uuid_encodes_as_big_endian_bytes(value: uuid.UUID) -> None:
    assert Writer().uuid(value).to_bytes() == value.bytes


@pytest.mark.parametrize("value", [NIL_UUID, SAMPLE_UUID])
def test_uuid_decodes_big_endian_bytes(value: uuid.UUID) -> None:
    assert Reader(value.bytes).uuid() == value


@pytest.mark.parametrize("value", [str(SAMPLE_UUID), SAMPLE_UUID.bytes, SAMPLE_UUID.int, None])
def test_uuid_writer_raises_unless_given_a_uuid(value: object) -> None:
    with pytest.raises(WireError, match="expected a UUID"):
        Writer().uuid(cast("uuid.UUID", value))


def test_uuid_reader_raises_on_truncated_input() -> None:
    with pytest.raises(WireError):
        Reader(SAMPLE_UUID.bytes[:-1]).uuid()


# Reader.expect_end(): lets a strict decoder assert it consumed the payload
# exactly, per PLAN.md's "decode must consume the payload exactly".


def test_expect_end_passes_when_fully_consumed() -> None:
    reader = Reader(bytes([1]))
    reader.var_int()
    reader.expect_end()  # must not raise


def test_expect_end_raises_when_bytes_remain() -> None:
    reader = Reader(bytes([1, 2, 3]))
    reader.var_int()
    with pytest.raises(WireError):
        reader.expect_end()


def test_expect_end_passes_on_empty_reader() -> None:
    Reader(b"").expect_end()  # must not raise


# Reader.remaining: the count of unconsumed bytes.


def test_remaining_is_full_length_before_reading() -> None:
    assert Reader(bytes([1, 2, 3])).remaining == 3


def test_remaining_shrinks_as_values_are_read() -> None:
    reader = Reader(bytes([1, 2, 3]))
    reader.var_int()
    assert reader.remaining == 2


def test_remaining_is_zero_when_fully_consumed() -> None:
    reader = Reader(bytes([1]))
    reader.var_int()
    assert reader.remaining == 0
