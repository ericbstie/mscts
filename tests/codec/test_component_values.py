"""The value of each data component, one row per layout (26.3 javap).

Every payload is built by hand from docs/research/2026-09-30-item-stacks.md, with the id that
note lists for the component (an independent check of the generated name list), not produced by
the Codec. A row is read from, and written back to, a stack of item 55 with that one component
added, so the type id, the value and the bytes after it are all pinned together.
"""

import pytest
from support.items import stack, stack_with_component
from support.wire import read_all, written

from mscts.codec.items import SLOT
from mscts.codec.wire import WireError

TEXT_A = "08 0001 61"  # a String tag "a": a text component
TEXT_B = "08 0001 62"


# (type id, name, payload hex, value)
VALUES = [
    pytest.param(
        5,
        "use_effects",
        "01 00 3f800000",
        {"can_sprint": True, "interact_vibrations": False, "speed_multiplier": 1.0},
        id="use_effects",
    ),
    pytest.param(
        11,
        "lore",
        f"02 {TEXT_A} {TEXT_B}",
        [bytes.fromhex(TEXT_A), bytes.fromhex(TEXT_B)],
        id="lore",
    ),
    pytest.param(
        13,
        "enchantments",
        "02 0c 05 c9 08 01",
        [{"enchantment": 12, "level": 5}, {"enchantment": 1097, "level": 1}],
        id="enchantments",
    ),
    pytest.param(
        45,
        "stored_enchantments",
        "01 00 02",
        [{"enchantment": 0, "level": 2}],
        id="stored_enchantments",
    ),
    pytest.param(
        17,
        "custom_model_data",
        "01 3f800000  02 01 00  01 03 61 62 63  01 00 ff 00 00",
        {"floats": [1.0], "flags": [True, False], "strings": ["abc"], "colors": [0xFF0000]},
        id="custom_model_data",
    ),
    pytest.param(
        18,
        "tooltip_display",
        "01 02 0d 15",
        {"hide_tooltip": True, "hidden_components": [13, 21]},
        id="tooltip_display",
    ),
    pytest.param(
        23,
        "food",
        "04 40000000 01",
        {"nutrition": 4, "saturation": 2.0, "can_always_eat": True},
        id="food",
    ),
    pytest.param(
        26,
        "use_cooldown",
        "3fc00000 01 03 61 3a 62",
        {"seconds": 1.5, "group": "a:b"},
        id="use_cooldown with a group",
    ),
    pytest.param(
        26, "use_cooldown", "3fc00000 00", {"seconds": 1.5, "group": None}, id="use_cooldown alone"
    ),
    pytest.param(
        29,
        "weapon",
        "02 40800000",
        {"damage_per_attack": 2, "disable_blocking_for": 4.0},
        id="weapon",
    ),
    pytest.param(
        30,
        "attack_range",
        "3f000000 3f800000 3fc00000 40000000 40200000 40400000",
        {
            "min_reach": 0.5,
            "max_reach": 1.0,
            "min_creative_reach": 1.5,
            "max_creative_reach": 2.0,
            "hitbox_margin": 2.5,
            "mob_factor": 3.0,
        },
        id="attack_range",
    ),
    pytest.param(40, "attack_animation", "01 14", {"type": 1, "duration": 20}, id="attack"),
    pytest.param(41, "interact_animation", "02 0a", {"type": 2, "duration": 10}, id="interact"),
    pytest.param(
        55,
        "suspicious_stew_effects",
        "01 05 c8 01",
        [{"effect": 5, "duration": 200}],
        id="suspicious_stew_effects",
    ),
    pytest.param(
        56,
        "writable_book_content",
        "02  01 61 00  01 62 01 01 63",
        [{"raw": "a", "filtered": None}, {"raw": "b", "filtered": "c"}],
        id="writable_book_content",
    ),
    pytest.param(
        78,
        "block_state",
        "01 05 6c 65 76 65 6c 01 31",
        [{"name": "level", "value": "1"}],
        id="block_state",
    ),
]


@pytest.mark.parametrize(("type_id", "name", "payload", "value"), VALUES)
def test_a_component_value_is_read_and_written_as_its_layout(
    type_id: int, name: str, payload: str, value: object
) -> None:
    encoded = stack_with_component(type_id, payload)
    assert read_all(SLOT, encoded) == stack(1, 55, **{name: value})
    assert written(SLOT, stack(1, 55, **{name: value})) == encoded


# Limits: `lore` is `List<=256`, `writable_book_content` `List<=100` (ByteBufCodecs.list(max)).


@pytest.mark.parametrize(
    ("type_id", "limit"), [(11, 256), (56, 100)], ids=["lore", "writable_book_content"]
)
def test_a_list_longer_than_its_maximum_is_refused(type_id: int, limit: int) -> None:
    over = limit + 1
    length = bytearray()
    while over > 0x7F:
        length.append((over & 0x7F) | 0x80)
        over >>= 7
    length.append(over)
    with pytest.raises(WireError, match=rf"exceeds max {limit}"):
        read_all(SLOT, stack_with_component(type_id, length.hex()))


# A realistic stack: `/give @s minecraft:diamond_sword[enchantments={sharpness:5}, damage=3,
# custom_name="Excalibur", lore=["x"]]`. Item 1050 is the diamond sword in the generated
# registries report; the enchantment ids are dynamic, so 12 stands for sharpness here.


def test_a_diamond_sword_with_enchantments_damage_a_custom_name_and_lore() -> None:
    excalibur = "08 0009 45 78 63 61 6c 69 62 75 72"
    encoded = bytes.fromhex(
        "01 9a 08"  # count 1, item 1050
        "04 00"  # four added, none removed
        "0d 01 0c 05"  # enchantments: {12: 5}
        "03 03"  # damage 3
        f"06 {excalibur}"  # custom_name
        "0b 01 08 00 01 78"  # lore: ["x"]
    )
    value = stack(
        1,
        1050,
        enchantments=[{"enchantment": 12, "level": 5}],
        damage=3,
        custom_name=bytes.fromhex(excalibur),
        lore=[bytes.fromhex("08 0001 78")],
    )
    assert read_all(SLOT, encoded) == value
    assert written(SLOT, value) == encoded
