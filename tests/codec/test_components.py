"""The data component table and the patch that carries it (`DataComponentPatch`, 26.3 javap).

The hex payloads are built by hand from the layouts in docs/research/2026-09-30-item-stacks.md,
not produced by the Codec. These tests use a three-component table of their own, so they say
nothing about which components the Target has: the coverage test below, and
tests/codec/test_slot.py, do.
"""

import pytest
from support.wire import read_all, written

from mscts.codec.components import TABLE as TARGET_TABLE
from mscts.codec.components import ComponentTable, Patch
from mscts.codec.registry_names import registry_names
from mscts.codec.schema import VAR_INT, SchemaError
from mscts.codec.wire import WireError
from mscts.target import TARGET

NAMES = ("minecraft:a", "minecraft:b", "minecraft:c")
# `a` is a VarInt, `b` is not network-synchronised, `c` has no layout in the table yet.
TABLE = ComponentTable(NAMES, {"minecraft:a": VAR_INT, "minecraft:b": None})
PATCH = Patch(TABLE)

EMPTY = {"added": [], "removed": []}


def test_the_table_maps_names_to_ids_and_back() -> None:
    assert TABLE.names == NAMES
    assert [TABLE.type_id(name) for name in NAMES] == [0, 1, 2]
    assert [TABLE.type_name(type_id) for type_id in range(3)] == list(NAMES)


def test_the_table_lists_the_types_it_has_no_entry_for() -> None:
    # `a` has a layout and `b` is marked not network-synchronised: both are entries. `c` is not.
    assert TABLE.without_layout == ("minecraft:c",)


def test_every_data_component_type_of_the_target_has_an_entry_in_the_real_table() -> None:
    names = registry_names(TARGET.minecraft_version, "minecraft:data_component_type")
    assert len(names) == 122
    assert TARGET_TABLE.names == names
    assert TARGET_TABLE.without_layout == ()


def test_a_layout_for_a_name_the_table_lacks_is_refused_when_declared() -> None:
    with pytest.raises(SchemaError, match="minecraft:typo"):
        ComponentTable(NAMES, {"minecraft:typo": VAR_INT})


def test_an_empty_patch_is_two_zero_counts() -> None:
    assert read_all(PATCH, b"\x00\x00") == EMPTY
    assert written(PATCH, EMPTY) == b"\x00\x00"


def test_a_patch_is_both_counts_then_the_added_pairs_then_the_removed_types() -> None:
    # added: one pair (type a, VarInt 5); removed: b and c. Removing needs no layout.
    encoded = bytes.fromhex("01 02 00 05 01 02")
    value = {
        "added": [{"type": "minecraft:a", "value": 5}],
        "removed": ["minecraft:b", "minecraft:c"],
    }
    assert read_all(PATCH, encoded) == value
    assert written(PATCH, value) == encoded


def test_a_patch_keeps_the_order_and_a_repeated_type_as_they_are_on_the_wire() -> None:
    encoded = bytes.fromhex("02 00 00 06 00 05")
    value = {
        "added": [{"type": "minecraft:a", "value": 6}, {"type": "minecraft:a", "value": 5}],
        "removed": [],
    }
    assert read_all(PATCH, encoded) == value
    assert written(PATCH, value) == encoded


def test_an_added_unknown_type_id_is_a_wire_error_naming_it() -> None:
    with pytest.raises(WireError, match=r"^added: 0: unknown data component type id 9$"):
        read_all(PATCH, bytes.fromhex("01 00 09 00"))


def test_a_removed_unknown_type_id_is_a_wire_error_naming_it() -> None:
    with pytest.raises(WireError, match=r"^removed: 0: unknown data component type id 9$"):
        read_all(PATCH, bytes.fromhex("00 01 09"))


def test_an_added_component_that_is_not_network_synchronised_is_a_wire_error_naming_it() -> None:
    with pytest.raises(WireError, match=r"^added: 0: data component minecraft:b is not network-"):
        read_all(PATCH, bytes.fromhex("01 00 01"))


def test_an_added_component_with_no_layout_is_a_wire_error_naming_it() -> None:
    with pytest.raises(WireError, match=r"^added: 0: data component minecraft:c has no known"):
        read_all(PATCH, bytes.fromhex("01 00 02"))


def test_a_value_error_names_the_pair_and_the_component() -> None:
    # The second pair's VarInt never ends.
    with pytest.raises(WireError, match=r"^added: 1: minecraft:a: "):
        read_all(PATCH, bytes.fromhex("02 00 00 05 00 80"))


@pytest.mark.parametrize(
    "encoded", ["ffffffff0f 00", "00 ffffffff0f"], ids=["added count", "removed count"]
)
def test_a_negative_count_is_refused(encoded: str) -> None:
    with pytest.raises(WireError, match="negative"):
        read_all(PATCH, bytes.fromhex(encoded))


# One more than the bytes left, and every entry takes at least one.
@pytest.mark.parametrize("encoded", ["02 00 00", "00 02 00"], ids=["added count", "removed count"])
def test_a_count_larger_than_the_bytes_left_is_refused_before_reading_any_entry(
    encoded: str,
) -> None:
    with pytest.raises(WireError, match="exceeds"):
        read_all(PATCH, bytes.fromhex(encoded))


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ({"added": [{"type": "minecraft:zzz", "value": 1}], "removed": []}, r"^added: 0: unknown"),
        ({"added": [{"type": "minecraft:b", "value": 1}], "removed": []}, r"^added: 0: .*b is not"),
        ({"added": [{"type": "minecraft:c", "value": 1}], "removed": []}, r"^added: 0: .*c has no"),
        ({"added": [], "removed": ["minecraft:zzz"]}, r"^removed: 0: unknown"),
        ({"added": [{"type": "minecraft:a", "value": "x"}], "removed": []}, r"^added: 0: .*a: "),
        ({"added": [{"type": "minecraft:a"}], "removed": []}, r"^added: 0: missing key value"),
        (
            {"added": [{"type": "minecraft:a", "value": 1, "x": 1}], "removed": []},
            "unexpected key x",
        ),
        ({"added": [5], "removed": []}, r"^added: 0: expected a mapping"),
        ({"added": [], "removed": [5]}, r"^removed: 0: expected a str"),
        ({"added": []}, "missing key removed"),
        ({"added": [], "removed": [], "extra": 1}, "unexpected key extra"),
        ([], "expected a mapping"),
        ({"added": 5, "removed": []}, r"^added: expected a list"),
    ],
    ids=[
        "unknown added type",
        "not synchronised",
        "no layout",
        "unknown removed type",
        "bad value",
        "missing value key",
        "extra pair key",
        "pair not a mapping",
        "removed not a str",
        "missing removed",
        "extra patch key",
        "patch not a mapping",
        "added not a list",
    ],
)
def test_a_patch_that_does_not_fit_is_refused_when_written(value: object, message: str) -> None:
    with pytest.raises(WireError, match=message):
        written(PATCH, value)
