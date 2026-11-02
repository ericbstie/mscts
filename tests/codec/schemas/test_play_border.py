"""The world border schemas, round-tripped through hand-built bytes.

The layouts are the 26.3 javap of each packet's `write` and its reading constructor
(the fact sheet of #68).
"""

import pytest
from support.play import round_trip_packet
from support.wire import doubles

from mscts.case_titles import TITLES
from mscts.codec.packets import Direction
from mscts.codec.schemas.play.border import CLIENTBOUND as BORDER

CLIENTBOUND = Direction.CLIENTBOUND

INITIALIZE_BORDER, SET_BORDER_CENTER, SET_BORDER_LERP_SIZE = 44, 90, 91
SET_BORDER_SIZE, SET_BORDER_WARNING_DELAY, SET_BORDER_WARNING_DISTANCE = 92, 93, 94


def test_initialize_border_is_the_centre_the_sizes_the_lerp_and_the_warnings() -> None:
    # A join in the middle of a lerp from 28 to 40 with 6 ticks left: the Reference's sizes, and
    # a lerp time of 6 ticks, a VarLong. The limit is 29999984; the warnings are the default.
    fields = {
        "center_x": 0.0,
        "center_z": 0.0,
        "old_size": 28.0,
        "new_size": 40.0,
        "lerp_time": 6,
        "absolute_max_size": 29999984,
        "warning_blocks": 5,
        "warning_time": 300,
    }
    data = (
        bytes([INITIALIZE_BORDER])
        + doubles(0.0, 0.0, 28.0, 40.0)
        + bytes([6])
        + bytes.fromhex("f086a70e")
        + bytes([5])
        + bytes.fromhex("ac02")
    )
    round_trip_packet(CLIENTBOUND, "minecraft:initialize_border", fields, data)


def test_set_border_size_is_the_size() -> None:
    data = bytes([SET_BORDER_SIZE]) + doubles(20.0)
    round_trip_packet(CLIENTBOUND, "minecraft:set_border_size", {"size": 20.0}, data)


def test_set_border_lerp_size_is_the_old_size_the_new_size_and_the_ticks_it_takes() -> None:
    fields = {"old_size": 20.0, "new_size": 40.0, "lerp_time": 5}
    data = bytes([SET_BORDER_LERP_SIZE]) + doubles(20.0, 40.0) + bytes([5])
    round_trip_packet(CLIENTBOUND, "minecraft:set_border_lerp_size", fields, data)


def test_set_border_lerp_size_reads_a_lerp_of_more_than_a_byte_as_a_var_long() -> None:
    fields = {"old_size": 20.0, "new_size": 40.0, "lerp_time": 6000}
    data = bytes([SET_BORDER_LERP_SIZE]) + doubles(20.0, 40.0) + bytes.fromhex("f02e")
    round_trip_packet(CLIENTBOUND, "minecraft:set_border_lerp_size", fields, data)


def test_set_border_center_is_the_x_then_the_z() -> None:
    data = bytes([SET_BORDER_CENTER]) + doubles(10.5, -3.5)
    round_trip_packet(
        CLIENTBOUND, "minecraft:set_border_center", {"center_x": 10.5, "center_z": -3.5}, data
    )


@pytest.mark.parametrize(
    ("name", "field", "packet_id"),
    [
        ("minecraft:set_border_warning_delay", "warning_delay", SET_BORDER_WARNING_DELAY),
        ("minecraft:set_border_warning_distance", "warning_blocks", SET_BORDER_WARNING_DISTANCE),
    ],
)
def test_the_warnings_are_a_var_int(name: str, field: str, packet_id: int) -> None:
    round_trip_packet(CLIENTBOUND, name, {field: 300}, bytes([packet_id]) + bytes.fromhex("ac02"))


def test_every_border_packet_and_field_has_a_test_case_title() -> None:
    # The Comparison names a test case by the packet and the field, so a field without a title
    # would show in a Report by its bare name.
    names = {
        name
        for packet, schema in BORDER.items()
        for name in (
            packet.removeprefix("minecraft:"),
            *(f"{packet.removeprefix('minecraft:')}.{field}" for field in schema.fields),
        )
    }

    assert sorted(names - TITLES.keys()) == []
