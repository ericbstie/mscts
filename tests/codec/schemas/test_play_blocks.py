"""The block packets of Target 26.3: each decodes into named fields and re-encodes byte for byte.

Layouts come from the 26.3 jar (`javap` on each packet's `STREAM_CODEC`) and the wiki (revision
3799543), which agree (docs/research/2026-10-01-block-world-events.md). The payloads are recorded
from vanilla 26.3, each named for the command that caused it, except `block_destruction`, which no
command makes vanilla send: that one is built by hand from the layout.
"""

import re
from typing import cast

import pytest
from support.play import CLIENTBOUND, CODEC, frame, round_trip

from mscts.codec.packets import CodecError, State
from mscts.codec.schema import ENTITY_ID
from mscts.codec.schemas import play

BLOCK_UPDATE = "minecraft:block_update"
SECTION_BLOCKS_UPDATE = "minecraft:section_blocks_update"
BLOCK_ENTITY_DATA = "minecraft:block_entity_data"
BLOCK_EVENT = "minecraft:block_event"
BLOCK_DESTRUCTION = "minecraft:block_destruction"


def decode_error(name: str, payload: str) -> str:
    """Why the Codec refuses `payload` as packet `name`."""
    with pytest.raises(CodecError) as caught:
        CODEC.decode(State.PLAY, CLIENTBOUND, frame(name, payload))
    return str(caught.value)


def encode_error(name: str, fields: dict[str, object]) -> str:
    """Why the Codec refuses to encode `fields` as packet `name`."""
    with pytest.raises(CodecError) as caught:
        CODEC.encode(State.PLAY, CLIENTBOUND, name, fields)
    return str(caught.value)


# Block update: a position and a block state id. Recorded from `setblock 1 -60 1 minecraft:stone`
# (block state 1), and from a note block placed at 8 -60 8 (state 681).


def test_a_setblock_decodes_to_its_position_and_block_state() -> None:
    round_trip(
        BLOCK_UPDATE,
        {"pos": {"x": 1, "y": -60, "z": 1}, "block_state": 1},
        "0000004000001fc401",
    )


def test_a_note_block_placement_decodes_to_its_block_state() -> None:
    round_trip(
        BLOCK_UPDATE,
        {"pos": {"x": 8, "y": -60, "z": 8}, "block_state": 681},
        "0000020000008fc4a905",
    )


# Update section blocks: the section's position, then each changed block as a VarLong: its state
# id << 12, then its position in the section as x << 8 | z << 4 | y. The entries come in the order
# vanilla sent them (the order of a set), and decode to {x, y, z, state}.

FILL = "00000000000ffffc08a426b424a526b526b426a524a424b524"
"""`fill 2 -60 2 3 -59 3 minecraft:stone`: 8 blocks of state 1, in the section at y -4."""

FILL_BLOCKS = [
    # a426 is 0x1324: state 1, then x 3, z 2, y 4 (the block at 3 -60 2); and so on in order.
    {"x": 3, "y": 4, "z": 2, "state": 1},
    {"x": 2, "y": 4, "z": 3, "state": 1},
    {"x": 3, "y": 5, "z": 2, "state": 1},
    {"x": 3, "y": 5, "z": 3, "state": 1},
    {"x": 3, "y": 4, "z": 3, "state": 1},
    {"x": 2, "y": 5, "z": 2, "state": 1},
    {"x": 2, "y": 4, "z": 2, "state": 1},
    {"x": 2, "y": 5, "z": 3, "state": 1},
]
SPAWN_SECTION = {"x": 0, "y": -4, "z": 0}


def test_a_fill_decodes_its_blocks_to_positions_in_the_order_sent() -> None:
    round_trip(SECTION_BLOCKS_UPDATE, {"section": SPAWN_SECTION, "blocks": FILL_BLOCKS}, FILL)


def test_a_door_powered_by_a_redstone_block_decodes_its_two_halves() -> None:
    # An oak door at 12 -60 8, both halves, then a redstone block beside it. The VarLongs are
    # 4 bytes each, because a block state above 4095 shifted by 12 takes more than 21 bits.
    round_trip(
        SECTION_BLOCKS_UPDATE,
        {
            "section": SPAWN_SECTION,
            "blocks": [
                {"x": 12, "y": 5, "z": 8, "state": 7246},
                {"x": 12, "y": 4, "z": 8, "state": 7254},
            ],
        },
        "00000000000ffffc0285d9930e84d9950e",
    )


def test_a_tnt_explosion_decodes_its_96_blocks_of_air() -> None:
    payload = (
        "000003fffffffffc60d217c30fa115d3119115a211c311b213c217920fb115c1"
        "179211a113b217a2139117c315a30fc115a311c211c213a1119215b119b219c1"
        "13b21bc313b317a21992179219a315a313b315a215b311a319b113b313a117a2"
        "17a317b30fb20fb211b111a119f3168319f318f31483179319931b9317f31293"
        "15b319b31bb11781158215c319d31b830fc31b83119313c317f2148117930f82"
        "17931182199113d31783158211f216c219d3138213911992139111b215c215f3"
        "1a8313d215d315b30d"
    )
    packet = CODEC.decode(State.PLAY, CLIENTBOUND, frame(SECTION_BLOCKS_UPDATE, payload))
    assert packet.fields is not None
    blocks = cast("list[dict[str, int]]", packet.fields["blocks"])
    assert len(blocks) == 96
    assert {block["state"] for block in blocks} == {0}
    assert len({(block["x"], block["y"], block["z"]) for block in blocks}) == 96
    assert CODEC.encode(State.PLAY, CLIENTBOUND, SECTION_BLOCKS_UPDATE, packet.fields) == frame(
        SECTION_BLOCKS_UPDATE, payload
    )


def test_a_section_update_keeps_the_highest_block_state_and_position() -> None:
    # (2**31 - 1) << 12 | 0xFFF is 2**43 - 1: the most a VarLong entry holds, in seven bytes.
    round_trip(
        SECTION_BLOCKS_UPDATE,
        {
            "section": {"x": 0, "y": 0, "z": 0},
            "blocks": [{"x": 15, "y": 15, "z": 15, "state": 2**31 - 1}],
        },
        "0000000000000000 01 ffffffffffff01",
    )


def test_a_section_update_with_no_blocks_is_a_section_and_a_zero() -> None:
    round_trip(
        SECTION_BLOCKS_UPDATE,
        {"section": {"x": 3, "y": -1, "z": -2}, "blocks": []},
        "00000fffffefffff 00",
    )


@pytest.mark.parametrize(
    "entry",
    ["80808080808002", "ffffffffffffffffff01"],
    ids=["2**43", "-1"],
)
def test_a_section_update_refuses_an_entry_vanilla_cannot_send(entry: str) -> None:
    error = decode_error(SECTION_BLOCKS_UPDATE, "0000000000000000 01 " + entry)
    assert "blocks: 0: " in error
    assert "is not a block state id" in error


@pytest.mark.parametrize(
    ("block", "message"),
    [
        ({"x": 16, "y": 0, "z": 0, "state": 0}, "x: 16 out of range for 0 to 15"),
        ({"x": 0, "y": -1, "z": 0, "state": 0}, "y: -1 out of range for 0 to 15"),
        ({"x": 0, "y": 0, "z": 16, "state": 0}, "z: 16 out of range for 0 to 15"),
        ({"x": 0, "y": 0, "z": 0, "state": -1}, "state: -1 out of range for 0 to 2147483647"),
        ({"x": 0, "y": 0, "z": 0, "state": 2**31}, "state: 2147483648 out of range for 0 to"),
        ({"x": 0, "y": 0, "z": 0}, r"missing field\(s\) state"),
        ({"x": 0, "y": 0, "z": 0, "state": 0, "extra": 1}, r"unexpected field\(s\) extra"),
        ({"x": 0, "y": 0, "z": True, "state": 0}, "z: expected an int"),
    ],
)
def test_a_section_update_writes_only_a_block_vanilla_can_send(
    block: dict[str, object], message: str
) -> None:
    error = encode_error(SECTION_BLOCKS_UPDATE, {"section": SPAWN_SECTION, "blocks": [block]})
    assert "blocks: 0: " in error
    assert re.search(message, error), error


# Block entity data: a position, the block entity type (a registry id) and its data, an NBT
# compound. Recorded from `setblock 16 -60 8 minecraft:spawner` (type 9) and from a sign at
# 18 -60 8 given text with `data merge block` (type 7).

SPAWNER_TAG = (
    "0a0200114d61784e6561726279456e74697469657300060200135265717569726564506c617965725261"
    "6e6765001002000a537061776e436f756e74000402000d4d6178537061776e44656c6179032002000a53"
    "7061776e52616e6765000402000544656c6179001402000d4d696e537061776e44656c617900c800"
)
SIGN_TAG = (
    "0a0a00096261636b5f746578740100106861735f676c6f77696e675f7465787400080005636f6c6f7200"
    "05626c61636b0900086d65737361676573080000000400000000000000000001000869735f7761786564"
    "000a000a66726f6e745f746578740100106861735f676c6f77696e675f7465787400080005636f6c6f72"
    "0005626c61636b0900086d65737361676573080000000400042268692200022222000222220002222200"
    "00"
)


def test_a_spawner_decodes_to_its_type_and_its_nbt_compound() -> None:
    round_trip(
        BLOCK_ENTITY_DATA,
        {
            "pos": {"x": 16, "y": -60, "z": 8},
            "type": 9,
            "tag": bytes.fromhex(SPAWNER_TAG),
        },
        "0000040000008fc4 09 " + SPAWNER_TAG,
    )


def test_a_sign_with_text_decodes_to_its_type_and_its_nbt_compound() -> None:
    round_trip(
        BLOCK_ENTITY_DATA,
        {
            "pos": {"x": 18, "y": -60, "z": 8},
            "type": 7,
            "tag": bytes.fromhex(SIGN_TAG),
        },
        "0000048000008fc4 07 " + SIGN_TAG,
    )


def test_block_entity_data_keeps_an_empty_compound() -> None:
    round_trip(
        BLOCK_ENTITY_DATA,
        {"pos": {"x": 0, "y": 0, "z": 0}, "type": 0, "tag": bytes.fromhex("0a00")},
        "0000000000000000 00 0a00",
    )


def test_block_entity_data_refuses_a_root_that_is_not_a_compound() -> None:
    error = decode_error(BLOCK_ENTITY_DATA, "0000000000000000 00 0800026869")
    assert "must be a compound" in error


# Block event: a position, two Unsigned Bytes (the action and its parameter) and the block's
# registry id, which comes last. Recorded from a note block at 8 -60 8 (block 118) powered by a
# redstone block.


def test_a_note_block_played_by_a_redstone_block_decodes_its_block_event() -> None:
    round_trip(
        BLOCK_EVENT,
        {
            "pos": {"x": 8, "y": -60, "z": 8},
            "action_id": 0,
            "action_parameter": 0,
            "block": 118,
        },
        "0000020000008fc4 00 00 76",
    )


def test_a_block_event_keeps_the_largest_action_parameter_and_block() -> None:
    round_trip(
        BLOCK_EVENT,
        {
            "pos": {"x": 0, "y": 0, "z": 0},
            "action_id": 255,
            "action_parameter": 255,
            "block": 1097,
        },
        "0000000000000000 ff ff c908",
    )


@pytest.mark.parametrize("field", ["action_id", "action_parameter"])
def test_a_block_event_writes_an_action_of_one_unsigned_byte(field: str) -> None:
    fields: dict[str, object] = {
        "pos": {"x": 0, "y": 0, "z": 0},
        "action_id": 0,
        "action_parameter": 0,
        "block": 0,
    }
    fields[field] = 256
    assert f"{field}: 256 out of range" in encode_error(BLOCK_EVENT, fields)


# Block destruction (the wiki's Set Block Destroy Stage): the entity breaking the block, its
# position and the stage, an Unsigned Byte of which 0 to 9 show a crack. No command makes vanilla
# send it (another player's dig does), so this payload is built by hand from the layout.


def test_a_block_destruction_decodes_its_breaker_position_and_stage() -> None:
    round_trip(
        BLOCK_DESTRUCTION,
        {"entity_id": 7, "pos": {"x": 1, "y": -60, "z": 1}, "stage": 3},
        "07 0000004000001fc4 03",
    )


def test_a_block_destruction_keeps_a_stage_that_shows_no_crack() -> None:
    round_trip(
        BLOCK_DESTRUCTION,
        {"entity_id": 300, "pos": {"x": 1, "y": -60, "z": 1}, "stage": 255},
        "ac02 0000004000001fc4 ff",
    )


def test_the_breaker_of_a_block_destruction_is_an_entity_id() -> None:
    assert play.CLIENTBOUND[BLOCK_DESTRUCTION].fields["entity_id"] is ENTITY_ID
