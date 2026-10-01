"""The hashed slot a client sends (`HashedStack.STREAM_CODEC`, 26.3 javap).

It is the wire type only: the hashes are Ints the caller gives, and the Codec re-encodes them as
they are. Computing a component's hash is not its job (#28). The payloads are built by hand from
the layout in docs/research/2026-09-30-item-stacks.md: a Bool, then the item (a registry id), the
count, the added components as a type id and an Int hash each, then the removed type ids.
"""

import pytest
from support.items import NO_COMPONENTS
from support.wire import read_all, written

from mscts.codec.items import HASHED_SLOT
from mscts.codec.wire import WireError


def hashed(item: int, count: int, added: list[tuple[str, int]], removed: list[str]) -> object:
    return {
        "item": item,
        "count": count,
        "components": {
            "added": [{"type": name, "hash": value} for name, value in added],
            "removed": removed,
        },
    }


def test_an_absent_stack_is_one_false_byte() -> None:
    assert read_all(HASHED_SLOT, b"\x00") is None
    assert written(HASHED_SLOT, None) == b"\x00"


def test_a_stack_is_the_item_then_the_count_not_the_slots_order() -> None:
    # 3 of item 55 (a slot would read count 55 of item 3 from the same bytes).
    encoded = bytes.fromhex("01 37 03 00 00")
    value = {"item": 55, "count": 3, "components": NO_COMPONENTS}
    assert read_all(HASHED_SLOT, encoded) == value
    assert written(HASHED_SLOT, value) == encoded


def test_added_components_are_a_type_and_an_int_hash_and_removed_ones_a_type() -> None:
    # 2 of item 1097; added: damage (3) with hash 0x12345678 and enchantments (13) with hash -1;
    # removed: max_damage (2).
    encoded = bytes.fromhex("01 c9 08 02  02 03 12345678 0d ffffffff  01 02")
    value = hashed(
        1097,
        2,
        [("minecraft:damage", 0x12345678), ("minecraft:enchantments", -1)],
        ["minecraft:max_damage"],
    )
    assert read_all(HASHED_SLOT, encoded) == value
    assert written(HASHED_SLOT, value) == encoded


def test_a_hash_is_a_signed_int() -> None:
    encoded = bytes.fromhex("01 37 01  01 03 80000000  00")
    value = hashed(55, 1, [("minecraft:damage", -(2**31))], [])
    assert read_all(HASHED_SLOT, encoded) == value
    assert written(HASHED_SLOT, value) == encoded


def test_the_order_and_a_repeated_type_are_kept_as_they_are_on_the_wire() -> None:
    encoded = bytes.fromhex("01 37 01  02 0d 00000002 03 00000001  02 03 03")
    value = hashed(
        55,
        1,
        [("minecraft:enchantments", 2), ("minecraft:damage", 1)],
        ["minecraft:damage", "minecraft:damage"],
    )
    assert read_all(HASHED_SLOT, encoded) == value
    assert written(HASHED_SLOT, value) == encoded


@pytest.mark.parametrize(
    ("encoded", "message"),
    [
        ("01 37 01 81 02", r"^components: added: array length 257 exceeds max 256$"),
        ("01 37 01 00 81 02", r"^components: removed: array length 257 exceeds max 256$"),
    ],
    ids=["added", "removed"],
)
def test_more_than_256_added_or_removed_components_are_refused(encoded: str, message: str) -> None:
    with pytest.raises(WireError, match=message):
        read_all(HASHED_SLOT, bytes.fromhex(encoded))


def test_256_components_are_written_and_257_are_refused() -> None:
    types = ["minecraft:damage"] * 257
    exactly = hashed(55, 1, [], types[:256])
    assert read_all(HASHED_SLOT, written(HASHED_SLOT, exactly)) == exactly
    with pytest.raises(WireError, match=r"^components: removed: array length 257 exceeds max 256"):
        written(HASHED_SLOT, hashed(55, 1, [], types))
    with pytest.raises(WireError, match=r"^components: added: array length 257 exceeds max 256"):
        written(HASHED_SLOT, hashed(55, 1, [("minecraft:damage", 0)] * 257, []))


@pytest.mark.parametrize(
    ("encoded", "message"),
    [
        ("01 37 01 01 7a 00000000 00", r"^components: added: 0: type: unknown data component"),
        ("01 37 01 00 01 7a", r"^components: removed: 0: unknown data component type id 122$"),
        ("02", r"^invalid bool byte 0x02$"),
        ("01 37 01 01 03 000000", r"^components: added: 0: hash: int truncated$"),
    ],
    ids=["added type", "removed type", "present flag", "truncated hash"],
)
def test_bad_bytes_are_refused_naming_the_part(encoded: str, message: str) -> None:
    with pytest.raises(WireError, match=message):
        read_all(HASHED_SLOT, bytes.fromhex(encoded))


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (
            hashed(55, 1, [("minecraft:zzz", 0)], []),
            r"^components: added: 0: type: unknown data component type 'minecraft:zzz'$",
        ),
        (
            hashed(55, 1, [], ["minecraft:zzz"]),
            r"^components: removed: 0: unknown data component type 'minecraft:zzz'$",
        ),
        (
            hashed(55, 1, [("minecraft:damage", 2**31)], []),
            r"^components: added: 0: hash: .*out of range",
        ),
        (
            {
                "item": 55,
                "count": 1,
                "components": {"added": [{"type": "minecraft:damage", "hash": 1.5}], "removed": []},
            },
            r"^components: added: 0: hash: expected an int",
        ),
        ({"item": 55, "count": 1}, r"missing field\(s\) components"),
        ("stack", r"expected a mapping"),
    ],
    ids=["added type", "removed type", "hash range", "hash type", "missing field", "not a mapping"],
)
def test_a_value_that_does_not_fit_is_refused_when_written(value: object, message: str) -> None:
    with pytest.raises(WireError, match=message):
        written(HASHED_SLOT, value)
