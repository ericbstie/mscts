"""Handshake schemas of Target 26.3, round-tripped through hand-built bytes."""

from collections.abc import Mapping

import pytest

from mscts.codec.packets import Codec, CodecError, Direction, State

CODEC = Codec.load("26.3")

INTENTION = {
    "protocol_version": 777,
    "server_address": "localhost",
    "server_port": 25565,
    "intent": 1,
}
INTENTION_BYTES = bytes.fromhex(
    "00"  # packet id: minecraft:intention
    "8906"  # protocol_version: VarInt 777
    "09 6c6f63616c686f7374"  # server_address: String (255) "localhost"
    "63dd"  # server_port: Unsigned Short 25565
    "01"  # intent: VarInt Enum, 1 = Status
)


def _encode_intention(fields: Mapping[str, object]) -> bytes:
    return CODEC.encode(State.HANDSHAKE, Direction.SERVERBOUND, "minecraft:intention", fields)


def _decode(data: bytes) -> object:
    return CODEC.decode(State.HANDSHAKE, Direction.SERVERBOUND, data).fields


def test_intention_encodes_to_hand_built_bytes() -> None:
    assert _encode_intention(INTENTION) == INTENTION_BYTES


def test_intention_decodes_from_hand_built_bytes() -> None:
    packet = CODEC.decode(State.HANDSHAKE, Direction.SERVERBOUND, INTENTION_BYTES)
    assert packet.name == "minecraft:intention"
    assert packet.fields == INTENTION


def test_intention_server_address_is_at_most_255_code_units() -> None:
    longest = {**INTENTION, "server_address": "a" * 255}
    assert _decode(_encode_intention(longest)) == longest
    with pytest.raises(CodecError, match="server_address: string exceeds max length 255"):
        _encode_intention({**INTENTION, "server_address": "a" * 256})
