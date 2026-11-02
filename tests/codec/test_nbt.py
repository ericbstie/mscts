"""Decoding network NBT into values, as the vanilla client reads it (#335)."""

import pytest

from mscts.codec.nbt import Array, Numeric, decode
from mscts.codec.schema import NBT
from mscts.codec.wire import Reader, WireError


def named(tag_type: int, name: bytes, payload: bytes) -> bytes:
    """A compound entry: its type, its name (already modified UTF-8), its payload."""
    return bytes([tag_type]) + len(name).to_bytes(2, "big") + name + payload


def string(text: bytes) -> bytes:
    """A String payload: an unsigned short length, then the (modified UTF-8) bytes."""
    return len(text).to_bytes(2, "big") + text


def count(number: int) -> bytes:
    return number.to_bytes(4, "big", signed=True)


# One root tag of each type, by hand: the type byte, then its payload (wiki NBT; NbtIo).
EACH_TYPE = [
    pytest.param("00", None, id="end"),
    pytest.param("01 ff", Numeric("byte", -1), id="byte"),
    pytest.param("02 8000", Numeric("short", -32768), id="short"),
    pytest.param("03 00000004", Numeric("int", 4), id="int"),
    pytest.param("04 7fffffffffffffff", Numeric("long", 2**63 - 1), id="long"),
    pytest.param("05 3fc00000", Numeric("float", 1.5), id="float"),
    pytest.param("06 bff8000000000000", Numeric("double", -1.5), id="double"),
    pytest.param("07 00000002 01ff", Array("byte_array", (1, -1)), id="byte_array"),
    pytest.param("08 0002 6869", "hi", id="string"),
    pytest.param(
        "09 03 00000002 00000001 00000002", [Numeric("int", 1), Numeric("int", 2)], id="list"
    ),
    pytest.param("09 00 00000000", [], id="empty_list"),
    pytest.param(
        "0a" + named(8, b"text", string(b"x")).hex() + named(1, b"bold", b"\x01").hex() + "00",
        {"text": "x", "bold": Numeric("byte", 1)},
        id="compound",
    ),
    pytest.param("0b 00000001 ffffffff", Array("int_array", (-1,)), id="int_array"),
    pytest.param("0c 00000001 0000000000000005", Array("long_array", (5,)), id="long_array"),
]


@pytest.mark.parametrize(("hex_tag", "value"), EACH_TYPE)
def test_each_tag_type_decodes_to_its_value(hex_tag: str, value: object) -> None:
    assert decode(bytes.fromhex(hex_tag)) == value


@pytest.mark.parametrize(("hex_tag", "value"), EACH_TYPE)
def test_the_walker_reads_each_decoded_tag_whole(hex_tag: str, value: object) -> None:
    del value
    tag = bytes.fromhex(hex_tag)
    assert NBT.read(Reader(tag)) == tag


def test_a_number_is_kept_apart_from_another_type_and_from_a_string() -> None:
    byte_one, int_one, text_one = (
        decode(bytes.fromhex(hex_tag)) for hex_tag in ("0101", "0300000001", "08000131")
    )
    assert byte_one != int_one
    assert int_one != text_one
    assert Numeric("float", 1.0) != Numeric("double", 1.0)


def test_nested_lists_and_compounds_decode_whole() -> None:
    inner = named(9, b"extra", b"\x08" + count(2) + string(b"a") + string(b"b"))
    tag = b"\x0a" + named(10, b"hover", inner + b"\x00") + named(3, b"n", count(7)) + b"\x00"
    assert decode(tag) == {"hover": {"extra": ["a", "b"]}, "n": Numeric("int", 7)}


def test_a_repeated_compound_key_keeps_its_last_value_as_the_client_does() -> None:
    tag = b"\x0a" + named(8, b"text", string(b"a")) + named(8, b"text", string(b"b")) + b"\x00"
    assert decode(tag) == {"text": "b"}


@pytest.mark.parametrize(
    ("encoded", "text"),
    [
        pytest.param(b"\xc0\x80", "\x00", id="null as two bytes"),
        pytest.param(b"\xc3\xa9", "\xe9", id="two bytes"),
        pytest.param(b"\xe2\x82\xac", "€", id="three bytes"),
        pytest.param(b"\xed\xa0\xbd\xed\xb8\x80", "\U0001f600", id="a surrogate pair"),
        pytest.param(b"\xc1\x81", "A", id="an overlong form readUTF takes"),
    ],
)
def test_a_string_is_modified_utf_8_as_readutf_reads_it(encoded: bytes, text: str) -> None:
    assert decode(b"\x08" + string(encoded)) == text


@pytest.mark.parametrize(
    "encoded",
    [
        pytest.param(b"\xf0\x9f\x98\x80", id="four-byte UTF-8"),
        pytest.param(b"\x80", id="a lone continuation byte"),
        pytest.param(b"\xc3", id="a cut two-byte form"),
        pytest.param(b"\xe2\x82", id="a cut three-byte form"),
        pytest.param(b"\xc3\x28", id="a bad continuation"),
    ],
)
def test_a_string_readutf_refuses_does_not_decode(encoded: bytes) -> None:
    with pytest.raises(WireError, match="NBT: malformed modified UTF-8"):
        decode(b"\x08" + string(encoded))


MALFORMED = [
    "0d",
    "0a" + named(13, b"x", b"").hex() + "00",
    "09 00 00000001",
    "09 01 ffffffff",
    "07 ffffffff",
    "08 0005 6d73",
    "0a 01 0001 62",
    "0a",
    "",
]


@pytest.mark.parametrize("hex_tag", MALFORMED)
def test_a_tag_the_walker_refuses_does_not_decode(hex_tag: str) -> None:
    tag = bytes.fromhex(hex_tag)
    with pytest.raises(WireError, match="NBT:"):
        NBT.read(Reader(tag))
    with pytest.raises(WireError, match="NBT:"):
        decode(tag)


def test_bytes_after_the_tag_do_not_decode() -> None:
    with pytest.raises(WireError, match="NBT: 1 unconsumed byte"):
        decode(b"\x01\x00\x00")


def test_an_empty_list_of_any_element_type_decodes_as_the_walker_reads_it() -> None:
    tag = bytes.fromhex("09 0d 00000000")
    assert NBT.read(Reader(tag)) == tag
    assert decode(tag) == []


def lists(depth: int) -> bytes:
    """`depth` lists, each holding the next one, the last one empty."""
    return b"\x09" + b"\x09\x00\x00\x00\x01" * (depth - 1) + b"\x00" + bytes(4)


def test_a_tag_nests_at_most_512_deep_as_the_walker_and_vanilla_read_it() -> None:
    value = decode(lists(512))
    for _ in range(511):
        assert isinstance(value, list)
        (value,) = value
    assert value == []
    with pytest.raises(WireError, match="NBT: nested deeper than 512"):
        decode(lists(513))
