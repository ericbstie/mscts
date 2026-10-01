"""The item stack field (`ItemStack.OPTIONAL_STREAM_CODEC`, 26.3 javap).

The hex payloads are built by hand from the layouts and the ids in
docs/research/2026-09-30-item-stacks.md, not produced by the Codec, so the component ids here
are an independent check of the generated name list.
"""

import pytest
from support.wire import read_all, written

from mscts.codec.items import SLOT
from mscts.codec.wire import Reader, WireError

NO_COMPONENTS = {"added": [], "removed": []}


def stack(count: int, item: int, **components: object) -> dict[str, object]:
    """A stack of `count` of item id `item` with `components` added by (full) name."""
    added = [{"type": f"minecraft:{name}", "value": value} for name, value in components.items()]
    return {"count": count, "item": item, "components": {"added": added, "removed": []}}


def test_the_empty_stack_is_a_zero_count_and_nothing_after_it() -> None:
    assert read_all(SLOT, b"\x00") is None
    assert written(SLOT, None) == b"\x00"


def test_the_empty_stack_leaves_what_follows() -> None:
    reader = Reader(bytes.fromhex("00 07"))
    assert SLOT.read(reader) is None
    assert reader.remaining == 1


def test_a_stack_is_its_count_then_its_item_then_a_patch() -> None:
    # 3 of item 55, no components.
    encoded = bytes.fromhex("03 37 00 00")
    value = {"count": 3, "item": 55, "components": NO_COMPONENTS}
    assert read_all(SLOT, encoded) == value
    assert written(SLOT, value) == encoded


def test_an_item_id_is_a_varint() -> None:
    encoded = bytes.fromhex("01 c9 08 00 00")
    value = {"count": 1, "item": 1097, "components": NO_COMPONENTS}
    assert read_all(SLOT, encoded) == value
    assert written(SLOT, value) == encoded


def test_a_stack_leaves_what_follows_its_patch() -> None:
    reader = Reader(bytes.fromhex("01 37 00 00 07"))
    assert SLOT.read(reader) == {"count": 1, "item": 55, "components": NO_COMPONENTS}
    assert reader.remaining == 1


def test_an_added_component_is_its_type_id_then_its_value() -> None:
    # Component 3 is `damage`, a VarInt.
    encoded = bytes.fromhex("01 37 01 00 03 05")
    assert read_all(SLOT, encoded) == stack(1, 55, damage=5)
    assert written(SLOT, stack(1, 55, damage=5)) == encoded


def test_a_removed_component_is_its_type_id_and_nothing_else() -> None:
    # Component 1 is `max_stack_size`.
    encoded = bytes.fromhex("01 37 00 01 01")
    value = {
        "count": 1,
        "item": 55,
        "components": {"added": [], "removed": ["minecraft:max_stack_size"]},
    }
    assert read_all(SLOT, encoded) == value
    assert written(SLOT, value) == encoded


def test_added_and_removed_components_together() -> None:
    encoded = bytes.fromhex("02 37 02 01 03 05 14 01")
    value = {
        "count": 2,
        "item": 55,
        "components": {
            "added": [
                {"type": "minecraft:damage", "value": 5},
                {"type": "minecraft:creative_slot_lock", "value": None},
            ],
            "removed": ["minecraft:max_stack_size"],
        },
    }
    assert read_all(SLOT, encoded) == value
    assert written(SLOT, value) == encoded


# One component of each simple shape, by the id the research note lists for it.
SIMPLE_SHAPES = [
    pytest.param(3, "damage", "05", 5, id="VarInt"),
    pytest.param(4, "unbreakable", "", None, id="unit"),
    pytest.param(7, "minimum_attack_charge", "3f000000", 0.5, id="Float"),
    pytest.param(21, "enchantment_glint_override", "01", True, id="Bool"),
    pytest.param(47, "dyed_color", "00 ff 00 00", 0xFF0000, id="Int"),
    pytest.param(10, "item_model", "03 61 3a 62", "a:b", id="Identifier"),
    pytest.param(8, "damage_type", "c9 08", 1097, id="registry id"),
    pytest.param(12, "rarity", "02", 2, id="enum"),
    pytest.param(6, "custom_name", "08 0002 6869", bytes.fromhex("08 0002 6869"), id="text"),
    pytest.param(49, "map_decorations", "0a 00", bytes.fromhex("0a 00"), id="NBT"),
    pytest.param(121, "cushion/color", "0f", 15, id="the last id"),
]


@pytest.mark.parametrize(("type_id", "name", "payload", "value"), SIMPLE_SHAPES)
def test_each_simple_component_shape_round_trips(
    type_id: int, name: str, payload: str, value: object
) -> None:
    encoded = bytes.fromhex(f"01 37 01 00 {type_id:02x} {payload}")
    assert read_all(SLOT, encoded) == stack(1, 55, **{name: value})
    assert written(SLOT, stack(1, 55, **{name: value})) == encoded


def test_an_unknown_component_type_id_is_a_wire_error_naming_it() -> None:
    # The registry has 122 components, ids 0 to 121.
    message = r"^components: added: 0: unknown data component type id 122$"
    with pytest.raises(WireError, match=message):
        read_all(SLOT, bytes.fromhex("01 37 01 00 7a"))


def test_an_unknown_removed_type_id_is_a_wire_error_naming_it() -> None:
    message = r"^components: removed: 0: unknown data component type id 122$"
    with pytest.raises(WireError, match=message):
        read_all(SLOT, bytes.fromhex("01 37 00 01 7a"))


def test_a_text_component_that_is_a_tag_end_is_a_wire_error_naming_the_component() -> None:
    message = r"^components: added: 0: minecraft:custom_name: NBT: .*END"
    with pytest.raises(WireError, match=message):
        read_all(SLOT, bytes.fromhex("01 37 01 00 06 00"))


def test_a_negative_count_is_refused_though_vanilla_reads_it_as_empty() -> None:
    with pytest.raises(WireError, match=r"^count: -1 is negative"):
        read_all(SLOT, bytes.fromhex("ff ff ff ff 0f"))


def test_a_stack_cut_short_names_the_field() -> None:
    with pytest.raises(WireError, match=r"^item: "):
        read_all(SLOT, bytes.fromhex("01"))
    with pytest.raises(WireError, match=r"^components: "):
        read_all(SLOT, bytes.fromhex("01 37"))


@pytest.mark.parametrize("count", [0, -1])
def test_a_count_below_one_is_not_written_as_a_stack(count: int) -> None:
    with pytest.raises(WireError, match=rf"^count: {count} is not positive.*None"):
        written(SLOT, stack(count, 55))


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ({"count": 1, "item": 55}, "missing field.* components"),
        ({"count": 1, "item": 55, "components": NO_COMPONENTS, "x": 1}, "unexpected field.* x"),
        ([], "expected a mapping"),
        (stack(1, 55, damage="x"), r"^components: added: 0: minecraft:damage: expected an int"),
        ({"count": "1", "item": 55, "components": NO_COMPONENTS}, r"^count: expected an int"),
        ({"count": 1, "item": None, "components": NO_COMPONENTS}, r"^item: expected an int"),
    ],
    ids=["missing key", "extra key", "not a mapping", "bad component", "bad count", "bad item"],
)
def test_a_stack_that_does_not_fit_is_refused_when_written(value: object, message: str) -> None:
    with pytest.raises(WireError, match=message):
        written(SLOT, value)
