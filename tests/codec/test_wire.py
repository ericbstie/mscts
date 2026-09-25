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
