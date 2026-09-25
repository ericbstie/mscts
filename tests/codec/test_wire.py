import pytest

from mscts.codec.wire import Reader, Writer

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
