"""The tab list packets, round-tripped through bytes vanilla 26.3 sent (#67)."""

import uuid
from collections.abc import Mapping

import pytest

from mscts.codec.packets import Codec, CodecError, Direction, State

CODEC = Codec.load("26.3")
UPDATE = "minecraft:player_info_update"
REMOVE = "minecraft:player_info_remove"

BOB = uuid.UUID("8e289159-2034-3a16-96b9-9fa637848b3b")
"""bob's offline UUID, as vanilla wrote it in each packet below."""

BOB_JOINED = bytes.fromhex("47ff018e28915920343a1696b99fa637848b3b03626f620000000100000001")
"""What vanilla sent another player when bob joined: every action, one entry (live, #67)."""

ALL_ACTIONS = [
    "add_player",
    "initialize_chat",
    "update_game_mode",
    "update_listed",
    "update_latency",
    "update_display_name",
    "update_list_order",
    "update_hat",
]


def _decode(data: bytes) -> dict[str, object]:
    packet = CODEC.decode(State.PLAY, Direction.CLIENTBOUND, data)
    assert packet.fields is not None
    return dict(packet.fields)


def _encode(name: str, fields: Mapping[str, object]) -> bytes:
    return CODEC.encode(State.PLAY, Direction.CLIENTBOUND, name, fields)


def test_a_join_holds_every_action_for_the_new_player() -> None:
    fields = {
        "actions": ALL_ACTIONS,
        "players": [
            {
                "uuid": BOB,
                "name": "bob",
                "properties": [],
                "chat_session": None,
                "game_mode": 0,
                "listed": True,
                "ping": 0,
                "display_name": None,
                "priority": 0,
                "hat_visible": True,
            }
        ],
    }

    assert _decode(BOB_JOINED) == fields
    assert _encode(UPDATE, fields) == BOB_JOINED


def test_a_game_mode_change_holds_only_the_game_mode() -> None:
    data = bytes.fromhex("4704018e28915920343a1696b99fa637848b3b03")
    fields = {"actions": ["update_game_mode"], "players": [{"uuid": BOB, "game_mode": 3}]}

    assert _decode(data) == fields
    assert _encode(UPDATE, fields) == data


def test_a_chat_session_is_its_id_expiry_key_and_signature() -> None:
    session = {
        "session_id": BOB,
        "expires_at": 1_700_000_000_000,
        "public_key": [1, -2],
        "key_signature": [3],
    }
    fields = {"actions": ["initialize_chat"], "players": [{"uuid": BOB, "chat_session": session}]}

    data = _encode(UPDATE, fields)

    assert data == bytes.fromhex(
        "4702018e28915920343a1696b99fa637848b3b01"
        "8e28915920343a1696b99fa637848b3b"
        "0000018bcfe56800"
        "0201fe"
        "0103"
    )
    assert _decode(data) == fields


def test_a_player_leaving_is_the_list_of_uuids() -> None:
    data = bytes.fromhex("46018e28915920343a1696b99fa637848b3b")
    fields = {"uuids": [BOB]}

    assert _decode(data) == fields
    assert _encode(REMOVE, fields) == data


@pytest.mark.parametrize(
    ("actions", "match"),
    [
        (["update_hat", "add_player"], "in the order of their bits"),
        (["update_hat", "update_hat"], "in the order of their bits"),
        (["fly"], "unknown action 'fly'"),
        ("update_hat", "a list of action names"),
    ],
    ids=["out-of-order", "twice", "unknown", "not-a-list"],
)
def test_actions_the_bits_cannot_hold_are_refused(actions: object, match: str) -> None:
    fields = {"actions": actions, "players": []}

    with pytest.raises(CodecError, match=match):
        _encode(UPDATE, fields)


def test_an_entry_must_hold_exactly_the_fields_of_its_actions() -> None:
    fields = {"actions": ["update_hat"], "players": [{"uuid": BOB, "ping": 0}]}

    with pytest.raises(CodecError, match=r"missing field.*hat_visible"):
        _encode(UPDATE, fields)


def test_an_entry_cut_short_is_refused() -> None:
    with pytest.raises(CodecError, match="player_info_update"):
        CODEC.decode(State.PLAY, Direction.CLIENTBOUND, BOB_JOINED[:-1])
