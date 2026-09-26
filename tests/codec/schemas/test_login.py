"""Login schemas of Target 26.3, round-tripped through hand-built bytes."""

import uuid
from collections.abc import Mapping

import pytest

from mscts.codec.packets import Codec, CodecError, Direction, State

CODEC = Codec.load("26.3")
CLIENTBOUND, SERVERBOUND = Direction.CLIENTBOUND, Direction.SERVERBOUND
NOTCH = uuid.UUID("b50ad385-829d-3141-a216-7e7d7539ba7f")  # Notch's offline UUID (research)
SESSION = uuid.UUID("00112233-4455-6677-8899-aabbccddeeff")


def round_trip(direction: Direction, name: str, fields: Mapping[str, object], data: bytes) -> None:
    assert CODEC.encode(State.LOGIN, direction, name, fields) == data
    packet = CODEC.decode(State.LOGIN, direction, data)
    assert (packet.name, packet.fields) == (name, fields)


def test_hello_is_the_name_and_uuid() -> None:
    data = bytes.fromhex("00 05") + b"Notch" + NOTCH.bytes  # id 0x00, String (16), UUID
    round_trip(SERVERBOUND, "minecraft:hello", {"name": "Notch", "player_uuid": NOTCH}, data)


def test_hello_name_is_at_most_16() -> None:
    with pytest.raises(CodecError, match="name: string exceeds max length 16"):
        CODEC.encode(
            State.LOGIN, SERVERBOUND, "minecraft:hello", {"name": "x" * 17, "player_uuid": NOTCH}
        )


def test_login_acknowledged_has_no_fields() -> None:
    round_trip(SERVERBOUND, "minecraft:login_acknowledged", {}, bytes.fromhex("03"))


def test_login_compression_is_the_threshold() -> None:
    round_trip(
        CLIENTBOUND, "minecraft:login_compression", {"threshold": 256}, bytes.fromhex("03 8002")
    )
    round_trip(
        CLIENTBOUND,
        "minecraft:login_compression",
        {"threshold": -1},
        bytes.fromhex("03 ffffffff0f"),
    )


def test_login_finished_is_a_game_profile_and_a_session_id() -> None:
    profile = {
        "uuid": NOTCH,
        "username": "Notch",
        "properties": [
            {"name": "textures", "value": "e30=", "signature": None},
            {"name": "x", "value": "", "signature": "sig"},
        ],
    }
    data = (
        bytes.fromhex("02")  # id: minecraft:login_finished
        + NOTCH.bytes
        + bytes.fromhex("05")
        + b"Notch"
        + bytes.fromhex("02")  # two properties
        + bytes.fromhex("08")
        + b"textures"
        + bytes.fromhex("04")
        + b"e30="
        + bytes.fromhex("00")  # no signature
        + bytes.fromhex("01 78 00 01 03")
        + b"sig"
        + SESSION.bytes
    )
    round_trip(
        CLIENTBOUND, "minecraft:login_finished", {"profile": profile, "session_id": SESSION}, data
    )


def test_login_finished_allows_at_most_16_properties() -> None:
    property_ = {"name": "p", "value": "", "signature": None}
    profile = {"uuid": NOTCH, "username": "Notch", "properties": [property_] * 17}
    with pytest.raises(CodecError, match="profile: properties: array length 17 exceeds max 16"):
        CODEC.encode(
            State.LOGIN,
            CLIENTBOUND,
            "minecraft:login_finished",
            {"profile": profile, "session_id": SESSION},
        )
