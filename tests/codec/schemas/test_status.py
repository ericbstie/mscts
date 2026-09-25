"""Status schemas of Target 26.3, round-tripped through hand-built bytes."""

from collections.abc import Mapping

import pytest

from mscts.codec.packets import Codec, CodecError, Direction, Packet, State

CODEC = Codec.load("26.3")
CLIENTBOUND, SERVERBOUND = Direction.CLIENTBOUND, Direction.SERVERBOUND


def _encode(direction: Direction, name: str, fields: Mapping[str, object]) -> bytes:
    return CODEC.encode(State.STATUS, direction, name, fields)


def _decode(direction: Direction, data: bytes) -> Packet:
    return CODEC.decode(State.STATUS, direction, data)


def test_status_request_has_no_fields() -> None:
    assert _encode(SERVERBOUND, "minecraft:status_request", {}) == bytes.fromhex("00")
    packet = _decode(SERVERBOUND, bytes.fromhex("00"))
    assert packet.name == "minecraft:status_request"
    assert packet.fields == {}


def test_status_request_rejects_a_payload() -> None:
    with pytest.raises(CodecError, match=r"status_request: 1 unconsumed byte\(s\) remain"):
        _decode(SERVERBOUND, bytes.fromhex("00 00"))


STATUS_RESPONSE = {"json_response": '{"description":"mscts"}'}
STATUS_RESPONSE_BYTES = (
    bytes.fromhex(
        "00"  # packet id: minecraft:status_response
        "17"  # json_response: String (32767), VarInt byte length 23
    )
    + b'{"description":"mscts"}'
)


def test_status_response_encodes_to_hand_built_bytes() -> None:
    encoded = _encode(CLIENTBOUND, "minecraft:status_response", STATUS_RESPONSE)
    assert encoded == STATUS_RESPONSE_BYTES


def test_status_response_decodes_from_hand_built_bytes() -> None:
    packet = _decode(CLIENTBOUND, STATUS_RESPONSE_BYTES)
    assert packet.name == "minecraft:status_response"
    assert packet.fields == STATUS_RESPONSE


def test_status_response_json_is_at_most_32767_code_units() -> None:
    longest = {"json_response": "x" * 32767}
    encoded = _encode(CLIENTBOUND, "minecraft:status_response", longest)
    assert encoded[:4] == bytes.fromhex("00 ffff01")  # id, then VarInt byte length 32767
    assert _decode(CLIENTBOUND, encoded).fields == longest
    with pytest.raises(CodecError, match="json_response: string exceeds max length 32767"):
        _encode(CLIENTBOUND, "minecraft:status_response", {"json_response": "x" * 32768})
