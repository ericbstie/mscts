"""The chat schemas, round-tripped through hand-built bytes (26.3 javap, wiki revision 3790659)."""

import struct
import uuid
from collections.abc import Mapping

import pytest

from mscts.codec.packets import Codec, CodecError, Direction, State

CODEC = Codec.load("26.3")
CLIENTBOUND, SERVERBOUND = Direction.CLIENTBOUND, Direction.SERVERBOUND

SENDER = uuid.UUID("5627dd98-e6be-3c21-b8a8-e92344183641")
NAME = bytes([0x08, 0x00, 0x05]) + b"alice"  # an NBT String tag: the text "alice"
TEXT = bytes([0x08, 0x00, 0x02]) + b"hi"
SIGNATURE = bytes(range(256))


def long(value: int) -> bytes:
    return struct.pack(">q", value)


def round_trip(direction: Direction, name: str, fields: Mapping[str, object], data: bytes) -> None:
    assert CODEC.encode(State.PLAY, direction, name, fields) == data
    packet = CODEC.decode(State.PLAY, direction, data)
    assert (packet.name, packet.fields) == (name, fields)


def chat_fields(message: str) -> dict[str, object]:
    return {
        "message": message,
        "timestamp": 1_790_000_000_000,
        "salt": 7,
        "signature": None,
        "message_count": 0,
        "acknowledged": bytes(3),
        "checksum": 1,
    }


def test_chat_is_the_message_then_what_signs_it() -> None:
    data = (
        bytes([0x09, 0x02])
        + b"hi"
        + long(1_790_000_000_000)
        + long(7)
        + bytes([0x00, 0x00])
        + bytes(3)
        + bytes([0x01])
    )

    assert CODEC.packet_id(State.PLAY, SERVERBOUND, "minecraft:chat") == 0x09
    round_trip(SERVERBOUND, "minecraft:chat", chat_fields("hi"), data)


def test_a_signed_chat_carries_its_256_byte_signature() -> None:
    fields = chat_fields("hi") | {"signature": SIGNATURE}
    data = CODEC.encode(State.PLAY, SERVERBOUND, "minecraft:chat", fields)

    assert data[1 + 3 + 16 : 1 + 3 + 16 + 1 + 256] == bytes([0x01]) + SIGNATURE
    assert CODEC.decode(State.PLAY, SERVERBOUND, data).fields == fields


def test_the_acknowledged_set_is_always_3_bytes() -> None:
    with pytest.raises(CodecError, match=r"acknowledged: .*3"):
        CODEC.encode(
            State.PLAY, SERVERBOUND, "minecraft:chat", chat_fields("hi") | {"acknowledged": b"\0"}
        )


def test_a_chat_message_may_be_longer_than_the_server_reads() -> None:
    # Vanilla reads at most 256 characters and kicks for more; a Group sends more to test that.
    fields = chat_fields("x" * 257)

    data = CODEC.encode(State.PLAY, SERVERBOUND, "minecraft:chat", fields)

    assert CODEC.decode(State.PLAY, SERVERBOUND, data).fields == fields


def test_signed_chat_command_is_the_command_then_each_argument_s_signature() -> None:
    fields = {
        "command": "say hi",
        "timestamp": 1_790_000_000_000,
        "salt": 7,
        "argument_signatures": [{"argument_name": "message", "signature": SIGNATURE}],
        "message_count": 0,
        "acknowledged": bytes(3),
        "checksum": 1,
    }
    data = (
        bytes([0x08, 0x06])
        + b"say hi"
        + long(1_790_000_000_000)
        + long(7)
        + bytes([0x01, 0x07])
        + b"message"
        + SIGNATURE
        + bytes([0x00])
        + bytes(3)
        + bytes([0x01])
    )

    assert CODEC.packet_id(State.PLAY, SERVERBOUND, "minecraft:chat_command_signed") == 0x08
    round_trip(SERVERBOUND, "minecraft:chat_command_signed", fields, data)


def player_chat_fields(**changes: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "global_index": 3,
        "sender": SENDER,
        "index": 0,
        "signature": None,
        "message": "hi",
        "timestamp": 1_790_000_000_000,
        "salt": 0,
        "previous_messages": [],
        "unsigned_content": None,
        "filter": {"type": "pass_through", "bits": None},
        "chat_type": {"reference": 0},
        "sender_name": NAME,
        "target_name": None,
    }
    return fields | changes


def test_player_chat_is_a_header_a_body_then_how_to_show_it() -> None:
    data = (
        bytes([0x42, 0x03])
        + SENDER.bytes
        + bytes([0x00, 0x00, 0x02])
        + b"hi"
        + long(1_790_000_000_000)
        + long(0)
        + bytes([0x00, 0x00, 0x00, 0x01])
        + NAME
        + bytes([0x00])
    )

    assert CODEC.packet_id(State.PLAY, CLIENTBOUND, "minecraft:player_chat") == 0x42
    round_trip(CLIENTBOUND, "minecraft:player_chat", player_chat_fields(), data)


def test_player_chat_previous_messages_are_an_id_or_a_whole_signature() -> None:
    fields = player_chat_fields(
        signature=SIGNATURE,
        previous_messages=[{"reference": 4}, {"direct": SIGNATURE}],
        unsigned_content=TEXT,
        target_name=NAME,
    )

    data = CODEC.encode(State.PLAY, CLIENTBOUND, "minecraft:player_chat", fields)

    assert bytes([0x02, 0x05, 0x00]) + SIGNATURE in data
    assert CODEC.decode(State.PLAY, CLIENTBOUND, data).fields == fields


def test_player_chat_holds_at_most_20_previous_messages() -> None:
    fields = player_chat_fields(previous_messages=[{"reference": 0}] * 21)

    with pytest.raises(CodecError, match=r"previous_messages: .*20"):
        CODEC.encode(State.PLAY, CLIENTBOUND, "minecraft:player_chat", fields)


def test_a_partly_filtered_message_names_its_filtered_characters() -> None:
    fields = player_chat_fields(filter={"type": "partially_filtered", "bits": [5]})

    data = CODEC.encode(State.PLAY, CLIENTBOUND, "minecraft:player_chat", fields)

    assert bytes([0x02, 0x01]) + long(5) + bytes([0x01]) + NAME in data
    assert CODEC.decode(State.PLAY, CLIENTBOUND, data).fields == fields


DECORATION = {"translation_key": "chat.type.text", "parameters": [0, 2], "style": bytes([10, 0])}


def test_a_chat_type_can_be_written_in_place() -> None:
    fields = player_chat_fields(chat_type={"direct": {"chat": DECORATION, "narration": DECORATION}})
    decoration = bytes([0x0E]) + b"chat.type.text" + bytes([0x02, 0x00, 0x02, 10, 0])

    data = CODEC.encode(State.PLAY, CLIENTBOUND, "minecraft:player_chat", fields)

    assert bytes([0x00]) + decoration + decoration + NAME in data
    assert CODEC.decode(State.PLAY, CLIENTBOUND, data).fields == fields


def test_disguised_chat_is_the_message_then_how_to_show_it() -> None:
    fields = {
        "message": TEXT,
        "chat_type": {"reference": 1},
        "sender_name": NAME,
        "target_name": NAME,
    }
    data = bytes([0x21]) + TEXT + bytes([0x02]) + NAME + bytes([0x01]) + NAME

    assert CODEC.packet_id(State.PLAY, CLIENTBOUND, "minecraft:disguised_chat") == 0x21
    round_trip(CLIENTBOUND, "minecraft:disguised_chat", fields, data)
