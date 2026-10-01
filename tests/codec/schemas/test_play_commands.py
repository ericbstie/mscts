"""The play schemas a command travels in, round-tripped through hand-built bytes."""

import pytest

from mscts.codec.packets import Codec, CodecError, Direction, State

CODEC = Codec.load("26.3")
CLIENTBOUND, SERVERBOUND = Direction.CLIENTBOUND, Direction.SERVERBOUND


def test_chat_command_is_the_command_as_a_string() -> None:
    data = bytes([0x07, 0x0B]) + b"tick freeze"
    fields = {"command": "tick freeze"}

    assert CODEC.packet_id(State.PLAY, SERVERBOUND, "minecraft:chat_command") == 0x07
    assert CODEC.encode(State.PLAY, SERVERBOUND, "minecraft:chat_command", fields) == data
    packet = CODEC.decode(State.PLAY, SERVERBOUND, data)
    assert (packet.name, packet.fields) == ("minecraft:chat_command", fields)


def test_a_chat_command_holds_at_most_32767_characters() -> None:
    CODEC.encode(State.PLAY, SERVERBOUND, "minecraft:chat_command", {"command": "x" * 32767})
    with pytest.raises(CodecError, match=r"command: .*32767"):
        CODEC.encode(State.PLAY, SERVERBOUND, "minecraft:chat_command", {"command": "x" * 32768})


def test_system_chat_is_its_content_as_nbt_bytes_then_whether_it_is_an_overlay() -> None:
    content = bytes([0x08, 0x00, 0x02]) + b"hi"  # an NBT String tag: the text "hi"
    data = bytes([0x7C]) + content + bytes([0x01])
    fields = {"content": content, "overlay": True}

    assert CODEC.packet_id(State.PLAY, CLIENTBOUND, "minecraft:system_chat") == 0x7C
    assert CODEC.encode(State.PLAY, CLIENTBOUND, "minecraft:system_chat", fields) == data
    packet = CODEC.decode(State.PLAY, CLIENTBOUND, data)
    assert (packet.name, packet.fields) == ("minecraft:system_chat", fields)
