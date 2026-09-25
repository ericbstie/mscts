"""Codec.encode / Codec.decode driven by a Schema, on a synthetic packet table."""

import pytest

from mscts.codec.packets import Codec, CodecError, Direction, State
from mscts.codec.schema import LONG, USHORT, VAR_INT, Schema, String

STATE, DIRECTION = State.STATUS, Direction.SERVERBOUND
CODEC = Codec(
    {(STATE, DIRECTION): {"test:fields": 0x2A, "test:nested": 0x2B, "test:raw": 0x2C}},
    schemas={
        (STATE, DIRECTION): {
            "test:fields": Schema(number=VAR_INT, text=String(16), port=USHORT, stamp=LONG),
            "test:nested": Schema(outer=VAR_INT, inner=Schema(port=USHORT)),
        },
    },
)

FIELDS = {"number": 777, "text": "hi", "port": 25565, "stamp": -2}
DATA = bytes.fromhex(
    "2a"  # packet id
    "8906"  # number: VarInt 777
    "02 6869"  # text: String "hi"
    "63dd"  # port: UShort 25565
    "ffffffff fffffffe"  # stamp: Long -2
)


def test_encode_writes_the_packet_id_then_the_fields_in_schema_order() -> None:
    given_in_another_order = dict(reversed(FIELDS.items()))
    assert CODEC.encode(STATE, DIRECTION, "test:fields", given_in_another_order) == DATA


def test_decode_reads_the_fields_in_schema_order() -> None:
    packet = CODEC.decode(STATE, DIRECTION, DATA)
    assert packet.name == "test:fields"
    assert packet.payload == DATA[1:]
    assert packet.fields == FIELDS
    assert packet.fields is not None
    assert list(packet.fields) == list(FIELDS)


def test_a_schema_nests_as_a_compound_field() -> None:
    fields = {"outer": 1, "inner": {"port": 25565}}
    data = bytes.fromhex("2b 01 63dd")
    assert CODEC.encode(STATE, DIRECTION, "test:nested", fields) == data
    assert CODEC.decode(STATE, DIRECTION, data).fields == fields


def test_encode_of_packet_without_schema_raises() -> None:
    with pytest.raises(CodecError, match="status serverbound test:raw has no schema"):
        CODEC.encode(STATE, DIRECTION, "test:raw", {})


def test_decode_rejects_bytes_after_the_last_field() -> None:
    with pytest.raises(CodecError, match=r"test:fields: 1 unconsumed byte\(s\) remain"):
        CODEC.decode(STATE, DIRECTION, DATA + b"\x00")


def test_decode_rejects_a_payload_that_ends_inside_a_field() -> None:
    with pytest.raises(CodecError, match="status serverbound test:fields: stamp: long truncated"):
        CODEC.decode(STATE, DIRECTION, DATA[:-1])


def test_decode_error_in_a_nested_field_names_its_path() -> None:
    with pytest.raises(CodecError, match="test:nested: inner: port: ushort truncated"):
        CODEC.decode(STATE, DIRECTION, bytes.fromhex("2b 01 63"))


def test_encode_rejects_missing_fields() -> None:
    fields = {name: value for name, value in FIELDS.items() if name not in {"number", "port"}}
    with pytest.raises(CodecError, match=r"test:fields: missing field\(s\) number, port$"):
        CODEC.encode(STATE, DIRECTION, "test:fields", fields)


def test_encode_rejects_unexpected_fields() -> None:
    fields = {**FIELDS, "zeta": 1, "alpha": 2}
    with pytest.raises(CodecError, match=r"test:fields: unexpected field\(s\) alpha, zeta$"):
        CODEC.encode(STATE, DIRECTION, "test:fields", fields)


def test_encode_reports_missing_and_unexpected_fields_together() -> None:
    fields = {"outer": 1, "inner": {"prot": 25565}}
    with pytest.raises(
        CodecError,
        match=r"test:nested: inner: missing field\(s\) port; unexpected field\(s\) prot$",
    ):
        CODEC.encode(STATE, DIRECTION, "test:nested", fields)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("number", "777", "number: expected an int, got str"),
        ("number", True, "number: expected an int, got bool"),
        ("number", 2**31, "number: VarInt 2147483648 out of range"),
        ("port", -1, "port: ushort -1 out of range"),
        ("stamp", 2**63, "stamp: long 9223372036854775808 out of range"),
        ("text", 7, "text: expected a str, got int"),
        ("text", "x" * 17, "text: string exceeds max length 16"),
    ],
)
def test_encode_rejects_a_value_its_field_type_cannot_encode(
    field: str, value: object, error: str
) -> None:
    with pytest.raises(CodecError, match=f"test:fields: {error}"):
        CODEC.encode(STATE, DIRECTION, "test:fields", {**FIELDS, field: value})


def test_encode_rejects_a_non_mapping_for_a_compound_field() -> None:
    with pytest.raises(CodecError, match="test:nested: inner: expected a mapping"):
        CODEC.encode(STATE, DIRECTION, "test:nested", {"outer": 1, "inner": 25565})
