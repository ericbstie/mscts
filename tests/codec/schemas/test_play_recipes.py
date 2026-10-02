"""`update_recipes`: the property sets and the stonecutter's recipes a joining player gets.

The recorded payloads are what two fresh vanilla 26.3 Instances sent at a join (#30, worker
AR's join probe): the same recipes, with the property sets and their items in another order.
"""

from pathlib import Path
from typing import cast

import pytest

from mscts.codec.packets import Codec, CodecError, Direction, Packet, State
from mscts.codec.wire import Writer

CODEC = Codec.load("26.3")
CLIENTBOUND = Direction.CLIENTBOUND
NAME = "minecraft:update_recipes"
DATA = Path(__file__).parent / "data"
BOOTS = ("vanilla-26.3-boot1-update_recipes.bin", "vanilla-26.3-boot2-update_recipes.bin")


def _framed(payload: bytes) -> bytes:
    """`payload` behind the packet's id."""
    return Writer().var_int(CODEC.packet_id(State.PLAY, CLIENTBOUND, NAME)).to_bytes() + payload


def recorded(file: str) -> Packet:
    return CODEC.decode(State.PLAY, CLIENTBOUND, _framed((DATA / file).read_bytes()))


def _list(value: object) -> list[dict[str, object]]:
    assert isinstance(value, list)
    return cast("list[dict[str, object]]", value)


@pytest.mark.parametrize("file", BOOTS)
def test_a_recorded_join_decodes_and_encodes_byte_for_byte(file: str) -> None:
    packet = recorded(file)

    fields = packet.fields
    assert fields is not None
    sets = {entry["property_set_id"]: entry["items"] for entry in _list(fields["property_sets"])}
    assert len(sets) == 9
    assert len(cast("list[int]", sets["minecraft:furnace_input"])) == 163
    stonecutter = _list(fields["stonecutter_recipes"])
    assert len(stonecutter) == 351
    assert stonecutter[0] == {
        "ingredients": {"ids": [6]},
        "slot_display": {
            "type": "minecraft:item_stack",
            "value": {"item": 815, "count": 2, "components": {"added": [], "removed": []}},
        },
    }
    assert CODEC.encode(State.PLAY, CLIENTBOUND, NAME, fields) == _framed(packet.payload)


def _recipes(slot_display: dict[str, object]) -> dict[str, object]:
    return {
        "property_sets": [],
        "stonecutter_recipes": [
            {"ingredients": {"tag": "minecraft:logs"}, "slot_display": slot_display}
        ],
    }


ITEM = {"type": "minecraft:item", "value": 7}
SLOT_DISPLAYS = {
    "empty": ({"type": "minecraft:empty", "value": None}, b"\x00"),
    "any_fuel": ({"type": "minecraft:any_fuel", "value": None}, b"\x01"),
    "with_any_potion": ({"type": "minecraft:with_any_potion", "value": ITEM}, b"\x02\x04\x07"),
    "only_with_component": (
        {"type": "minecraft:only_with_component", "value": {"base": ITEM, "component_type": 3}},
        b"\x03\x04\x07\x03",
    ),
    "item": (ITEM, b"\x04\x07"),
    "item_stack": (
        {
            "type": "minecraft:item_stack",
            "value": {"item": 7, "count": 2, "components": {"added": [], "removed": []}},
        },
        b"\x05\x07\x02\x00\x00",
    ),
    "tag": ({"type": "minecraft:tag", "value": {"ids": [1, 2]}}, b"\x06\x03\x01\x02"),
    "dyed": (
        {"type": "minecraft:dyed", "value": {"dye": ITEM, "target": ITEM}},
        b"\x07\x04\x07\x04\x07",
    ),
    "smithing_trim": (
        {
            "type": "minecraft:smithing_trim",
            "value": {"base": ITEM, "material": ITEM, "pattern": {"reference": 2}},
        },
        b"\x08\x04\x07\x04\x07\x03",
    ),
    "smithing_trim_direct": (
        {
            "type": "minecraft:smithing_trim",
            "value": {
                "base": ITEM,
                "material": ITEM,
                "pattern": {
                    "direct": {
                        "asset_id": "minecraft:a",
                        "description": b"\x08\x00\x01P",  # network NBT: a string tag
                        "decal": True,
                    }
                },
            },
        },
        b"\x08\x04\x07\x04\x07\x00\x0bminecraft:a\x08\x00\x01P\x01",
    ),
    "with_remainder": (
        {"type": "minecraft:with_remainder", "value": {"ingredient": ITEM, "remainder": ITEM}},
        b"\x09\x04\x07\x04\x07",
    ),
    "composite": (
        {
            "type": "minecraft:composite",
            "value": [ITEM, {"type": "minecraft:empty", "value": None}],
        },
        b"\x0a\x02\x04\x07\x00",
    ),
}


@pytest.mark.parametrize(("slot_display", "data"), SLOT_DISPLAYS.values(), ids=SLOT_DISPLAYS.keys())
def test_each_slot_display_is_its_type_id_then_its_data(
    slot_display: dict[str, object], data: bytes
) -> None:
    # No property set; one stonecutter recipe: the tag minecraft:logs, then the slot display.
    payload = b"\x00\x01\x00\x0eminecraft:logs" + data
    fields = _recipes(slot_display)

    assert CODEC.encode(State.PLAY, CLIENTBOUND, NAME, fields) == _framed(payload)
    assert CODEC.decode(State.PLAY, CLIENTBOUND, _framed(payload)).fields == fields


def test_a_slot_display_of_no_known_type_is_refused() -> None:
    with pytest.raises(CodecError, match="unknown type id 11"):
        CODEC.decode(State.PLAY, CLIENTBOUND, _framed(b"\x00\x01\x00\x0eminecraft:logs\x0b"))


def test_a_property_set_is_its_id_then_its_items() -> None:
    fields = {
        "property_sets": [{"property_set_id": "minecraft:smoker_input", "items": [300, 1]}],
        "stonecutter_recipes": [],
    }
    payload = b"\x01\x16minecraft:smoker_input\x02\xac\x02\x01\x00"

    assert CODEC.encode(State.PLAY, CLIENTBOUND, NAME, fields) == _framed(payload)
    assert CODEC.decode(State.PLAY, CLIENTBOUND, _framed(payload)).fields == fields
