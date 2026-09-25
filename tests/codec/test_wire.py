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
