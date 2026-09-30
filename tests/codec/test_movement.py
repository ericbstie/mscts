"""The movement field types of the entity packets: each reads what it writes, and refuses the rest.

Layouts are from the 26.3 jar (`javap`): `ClientboundMoveEntityPacket` and `VecDelta` for the
move delta, `PositionPath` and `PositionStep` for the position path.
"""

import pytest

from mscts.codec.movement import MOVE_DELTA, POSITION_PATH
from mscts.codec.wire import Reader, WireError
from tests.codec.test_schema_types import read_all, written

# A move delta is a VarInt of properties (bit 0 on ground, the rest the number of steps), then
# with no steps three shorts (a change of position in 1/4096 of a block), else each step's ticks
# (a VarInt) and three shorts.

MOVE_DELTA_CASES = [
    # Recorded from vanilla 26.3 (the bytes after the entity id of move_entity_pos).
    ("00 0000 0000 0000", {"on_ground": False, "linear": {"x": 0, "y": 0, "z": 0}}),
    (
        "03 03 0000 0000 0000",
        {"on_ground": True, "stepped": [{"ticks": 3, "x": 0, "y": 0, "z": 0}]},
    ),
    # The bytes after the entity id of a move_entity_pos_rot, and before its two angles.
    ("00 0000 f0cd 0000", {"on_ground": False, "linear": {"x": 0, "y": -3891, "z": 0}}),
    (
        "03 03 fc6e 0000 fe21",
        {"on_ground": True, "stepped": [{"ticks": 3, "x": -914, "y": 0, "z": -479}]},
    ),
    # Built by hand: on the ground with a linear delta, the extremes of a short, and two steps
    # whose ticks need two bytes.
    ("01 7fff 8000 0001", {"on_ground": True, "linear": {"x": 32767, "y": -32768, "z": 1}}),
    (
        "04 01 0001 0002 0003 ac02 fffe 0000 0100",
        {
            "on_ground": False,
            "stepped": [
                {"ticks": 1, "x": 1, "y": 2, "z": 3},
                {"ticks": 300, "x": -2, "y": 0, "z": 256},
            ],
        },
    ),
]


@pytest.mark.parametrize(("encoded", "value"), MOVE_DELTA_CASES)
def test_move_delta_reads_and_writes_its_fields(encoded: str, value: dict[str, object]) -> None:
    assert read_all(MOVE_DELTA, bytes.fromhex(encoded)) == value
    assert written(MOVE_DELTA, value) == bytes.fromhex(encoded)


def test_move_delta_leaves_the_bytes_after_it_alone() -> None:
    reader = Reader(bytes.fromhex("00 000100020003 ff"))
    assert MOVE_DELTA.read(reader) == {"on_ground": False, "linear": {"x": 1, "y": 2, "z": 3}}
    assert reader.remaining == 1


@pytest.mark.parametrize(
    ("encoded", "error"),
    [
        ("", "truncated"),
        ("00 0000 0000", "truncated"),
        ("02 01 0000 0000", "truncated"),
        # Two steps announced, one there: the count is checked against the bytes left.
        ("05 01 0000 0000 0000", r"truncated: 2 step\(s\)"),
        # A count no packet could hold, from a negative VarInt read as unsigned.
        ("ffffffff0f 00", r"truncated: 2147483647 step\(s\)"),
    ],
)
def test_move_delta_refuses_what_is_not_there(encoded: str, error: str) -> None:
    with pytest.raises(WireError, match=error):
        read_all(MOVE_DELTA, bytes.fromhex(encoded))


@pytest.mark.parametrize(
    ("value", "error"),
    [
        ({"on_ground": True}, "expected exactly one of linear, stepped"),
        (
            {
                "on_ground": True,
                "linear": {"x": 0, "y": 0, "z": 0},
                "stepped": [{"ticks": 1, "x": 0, "y": 0, "z": 0}],
            },
            "expected exactly one of linear, stepped",
        ),
        ({"on_ground": True, "stepped": []}, "stepped: expected at least one step"),
        ({"linear": {"x": 0, "y": 0, "z": 0}}, r"missing field\(s\) on_ground"),
        ({"on_ground": 1, "linear": {"x": 0, "y": 0, "z": 0}}, "on_ground: expected a bool"),
        (
            {"on_ground": True, "linear": {"x": 32768, "y": 0, "z": 0}},
            "linear: x: short 32768 out of range",
        ),
        (
            {"on_ground": True, "linear": {"x": 0, "y": 0, "z": 0}, "extra": 1},
            r"unexpected field\(s\) extra",
        ),
        (
            {"on_ground": True, "stepped": [{"x": 0, "y": 0, "z": 0}]},
            r"stepped: 0: missing field\(s\) ticks",
        ),
        ((True, 1), "expected a mapping"),
    ],
)
def test_move_delta_refuses_what_it_cannot_encode(value: object, error: str) -> None:
    with pytest.raises(WireError, match=error):
        written(MOVE_DELTA, value)


# A position path is a VarInt type (0 linear, 1 stepped), then a linear end position (three
# Doubles) or a VarInt count of steps, each a position and a VarInt tick offset.

POSITION_PATH_CASES = [
    # Recorded from vanilla 26.3 (the bytes after the entity id of entity_position_sync).
    (
        "00 c01ef81b241038b5 c04e000000000000 c020636da16b3b47",
        {"linear": {"x": -7.742291034212191, "y": -60.0, "z": -8.194195789661206}},
    ),
    (
        "01 01 c016000000000000 c04e000000000000 c016000000000000 03",
        {"stepped": [{"x": -5.5, "y": -60.0, "z": -5.5, "tick_offset": 3}]},
    ),
    # Built by hand: two steps, the second with a tick offset of two bytes.
    (
        (
            "01 02 3ff0000000000000 0000000000000000 bff0000000000000 01 "
            "4000000000000000 4008000000000000 4010000000000000 ac02"
        ),
        {
            "stepped": [
                {"x": 1.0, "y": 0.0, "z": -1.0, "tick_offset": 1},
                {"x": 2.0, "y": 3.0, "z": 4.0, "tick_offset": 300},
            ]
        },
    ),
]


@pytest.mark.parametrize(("encoded", "value"), POSITION_PATH_CASES)
def test_position_path_reads_and_writes_its_fields(encoded: str, value: dict[str, object]) -> None:
    assert read_all(POSITION_PATH, bytes.fromhex(encoded)) == value
    assert written(POSITION_PATH, value) == bytes.fromhex(encoded)


def test_position_path_leaves_the_bytes_after_it_alone() -> None:
    reader = Reader(bytes.fromhex("00 3ff0000000000000 0000000000000000 bff0000000000000 ff"))
    assert POSITION_PATH.read(reader) == {"linear": {"x": 1.0, "y": 0.0, "z": -1.0}}
    assert reader.remaining == 1


@pytest.mark.parametrize(
    ("encoded", "error"),
    [
        ("", "truncated"),
        ("00 3ff0000000000000", "truncated"),
        # The client reads an unknown type as linear; here it is an error.
        ("02 3ff0000000000000 0000000000000000 bff0000000000000", "unknown type 2"),
        ("ffffffff0f", "unknown type -1"),
        # The client needs a last step to end the path at, and fails without one.
        ("01 00", "stepped: expected at least one step"),
        ("01 02 3ff0000000000000", "truncated"),
    ],
)
def test_position_path_refuses_what_is_not_valid(encoded: str, error: str) -> None:
    with pytest.raises(WireError, match=error):
        read_all(POSITION_PATH, bytes.fromhex(encoded))


@pytest.mark.parametrize(
    ("value", "error"),
    [
        ({}, "expected exactly one of linear, stepped"),
        (
            {
                "linear": {"x": 0.0, "y": 0.0, "z": 0.0},
                "stepped": [{"x": 0.0, "y": 0.0, "z": 0.0, "tick_offset": 1}],
            },
            "expected exactly one of linear, stepped",
        ),
        ({"stepped": []}, "stepped: expected at least one step"),
        ({"linear": {"x": 0.0, "y": 0.0}}, r"linear: missing field\(s\) z"),
        ({"linear": {"x": 0, "y": 0.0, "z": 0.0}}, "linear: x: expected a float"),
        ({"linear": {"x": 0.0, "y": 0.0, "z": 0.0}, "extra": 1}, r"unexpected field\(s\) extra"),
        ([1.0], "expected a mapping"),
    ],
)
def test_position_path_refuses_what_it_cannot_encode(value: object, error: str) -> None:
    with pytest.raises(WireError, match=error):
        written(POSITION_PATH, value)
