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
