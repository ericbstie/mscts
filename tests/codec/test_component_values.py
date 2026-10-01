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
    # Holder sets: a tag, or ids.
    pytest.param(27, "damage_resistant", "00 03 61 3a 62", {"tag": "a:b"}, id="damage_resistant"),
    pytest.param(33, "repairable", "03 05 06", {"ids": [5, 6]}, id="repairable"),
    pytest.param(67, "provides_banner_patterns", "01", {"ids": []}, id="provides_banner_patterns"),
    pytest.param(
        87,
        "mob_visibility",
        "00 03 61 3a 62 3f000000",
        {"targeting_entity_types": {"tag": "a:b"}, "visibility": 0.5},
        id="mob_visibility",
    ),
    # A sound event: a holder of an Identifier and an optional fixed range.
    pytest.param(83, "break_sound", "01", {"reference": 0}, id="break_sound reference"),
    pytest.param(
        83,
        "break_sound",
        "00 03 61 3a 62 01 3f800000",
        {"direct": {"location": "a:b", "fixed_range": 1.0}},
        id="break_sound inline with a range",
    ),
    pytest.param(
        83,
        "break_sound",
        "00 03 61 3a 62 00",
        {"direct": {"location": "a:b", "fixed_range": None}},
        id="break_sound inline",
    ),
    # Resolvable ints and floats: a constant or the Identifier of a context value.
    pytest.param(84, "compostable", "01 00 00 00 05", {"constant": 5}, id="compostable constant"),
    pytest.param(
        84, "compostable", "00 03 61 3a 62", {"reference": "a:b"}, id="compostable reference"
    ),
    pytest.param(
        85,
        "cooking_fuel",
        "01 00 00 07 d0  01 3f800000",
        {"burn_time": {"constant": 2000}, "speed_multiplier": {"constant": 1.0}},
        id="cooking_fuel",
    ),
    pytest.param(
        86,
        "brewing_fuel",
        "00 03 61 3a 62  01 40000000",
        {"uses": {"reference": "a:b"}, "speed_multiplier": {"constant": 2.0}},
        id="brewing_fuel",
    ),
    # Holders of a record: a registry id, or the record itself.
    pytest.param(64, "provides_trim_material", "01", {"reference": 0}, id="trim material id"),
    pytest.param(
        64,
        "provides_trim_material",
        f"00 03 61 3a 62 {TEXT_A}",
        {"direct": {"palette_id": "a:b", "description": bytes.fromhex(TEXT_A)}},
        id="trim material inline",
    ),
    pytest.param(
        58,
        "trim",
        f"01  00 03 61 3a 62 {TEXT_A} 01",
        {
            "material": {"reference": 0},
            "pattern": {
                "direct": {
                    "asset_id": "a:b",
                    "description": bytes.fromhex(TEXT_A),
                    "decal": True,
                }
            },
        },
        id="trim",
    ),
    pytest.param(63, "instrument", "2b", {"reference": 42}, id="instrument id"),
    pytest.param(
        63,
        "instrument",
        f"00  01 3f800000 40000000 05 {TEXT_A}",
        {
            "direct": {
                "sound_event": {"reference": 0},
                "use_duration": 1.0,
                "range": 2.0,
                "durability_damage": 5,
                "description": bytes.fromhex(TEXT_A),
            }
        },
        id="instrument inline",
    ),
    pytest.param(
        66,
        "jukebox_playable",
        f"00  01 {TEXT_A} 40a00000 0f",
        {
            "direct": {
                "sound_event": {"reference": 0},
                "description": bytes.fromhex(TEXT_A),
                "length_in_seconds": 5.0,
                "comparator_output": 15,
            }
        },
        id="jukebox_playable inline",
    ),
    pytest.param(
        74,
        "banner_patterns",
        "02  01 03  00 03 61 3a 62 01 7a 0e",
        [
            {"pattern": {"reference": 0}, "color": 3},
            {"pattern": {"direct": {"asset_id": "a:b", "translation_key": "z"}}, "color": 14},
        ],
        id="banner_patterns",
    ),
    pytest.param(
        109,
        "painting/variant",
        "00 04 02 03 61 3a 62 00 00",
        {
            "direct": {
                "width": 4,
                "height": 2,
                "asset_id": "a:b",
                "title": None,
                "author": None,
            }
        },
        id="painting/variant",
    ),
    pytest.param(
        72,
        "profile",
        "00  00 00 00  00 00 00 00",
        {
            "profile": {"partial": {"name": None, "id": None, "properties": []}},
            "skin_patch": {"body": None, "cape": None, "elytra": None, "slim": None},
        },
        id="profile",
    ),
    # Compound tags (`ByteBufCodecs.COMPOUND_TAG`), alone and behind an entity or block entity type.
    pytest.param(
        61, "bucket_entity_data", "0a 00", bytes.fromhex("0a 00"), id="bucket_entity_data"
    ),
    pytest.param(
        60,
        "entity_data",
        "c9 08 0a 00",
        {"type": 1097, "tag": bytes.fromhex("0a 00")},
        id="entity_data",
    ),
    pytest.param(
        62,
        "block_entity_data",
        "05 0a 00",
        {"type": 5, "tag": bytes.fromhex("0a 00")},
        id="block_entity_data",
    ),
    pytest.param(
        79,
        "bees",
        "01  02 0a 00  c8 01  64",
        [
            {
                "entity_data": {"type": 2, "tag": bytes.fromhex("0a 00")},
                "ticks_in_hive": 200,
                "min_ticks_in_hive": 100,
            }
        ],
        id="bees",
    ),
    # A lodestone's target is an optional global position: the dimension and a block position.
    pytest.param(
        69,
        "lodestone_tracker",
        "00 01",
        {"target": None, "tracked": True},
        id="lodestone_tracker without a target",
    ),
    pytest.param(
        69,
        "lodestone_tracker",
        "01 136d696e6563726166743a6f766572776f726c64 0000004000003002 00",
        {
            "target": {"dimension": "minecraft:overworld", "pos": {"x": 1, "y": 2, "z": 3}},
            "tracked": False,
        },
        id="lodestone_tracker with a target",
    ),
    # Fireworks: an explosion is its shape, two colour lists and two flags.
    pytest.param(
        70,
        "firework_explosion",
        "01  01 00 ff 00 00  00  01 00",
        {
            "shape": 1,
            "colors": [0xFF0000],
            "fade_colors": [],
            "has_trail": True,
            "has_twinkle": False,
        },
        id="firework_explosion",
    ),
    pytest.param(
        71,
        "fireworks",
        "02  01  01 01 00 ff 00 00  00  01 00",
        {
            "flight_duration": 2,
            "explosions": [
                {
                    "shape": 1,
                    "colors": [0xFF0000],
                    "fade_colors": [],
                    "has_trail": True,
                    "has_twinkle": False,
                }
            ],
        },
        id="fireworks",
    ),
    # A sign's text: four lines, optionally four filtered lines (no counts), a colour and glow.
    pytest.param(
        118,
        "sign_text_front",
        f"{TEXT_A} {TEXT_A} {TEXT_A} {TEXT_A}  00  0f 01",
        {
            "messages": [bytes.fromhex(TEXT_A)] * 4,
            "filtered_messages": None,
            "color": 15,
            "has_glowing_text": True,
        },
        id="sign_text_front",
    ),
    pytest.param(
        119,
        "sign_text_back",
        f"{TEXT_A} {TEXT_A} {TEXT_A} {TEXT_A}  01  {TEXT_B} {TEXT_B} {TEXT_B} {TEXT_B}  00 00",
        {
            "messages": [bytes.fromhex(TEXT_A)] * 4,
            "filtered_messages": [bytes.fromhex(TEXT_B)] * 4,
            "color": 0,
            "has_glowing_text": False,
        },
        id="sign_text_back",
    ),
    # Mob effects: an effect id and its details, which may hold a hidden effect (more details).
    pytest.param(
        53,
        "potion_contents",
        "01 05  01 00 ff 00 00  01  02 01 0a 00 01 01 01 00 05 00 00 00 00  01 01 61",
        {
            "potion": 5,
            "custom_color": 0xFF0000,
            "custom_effects": [
                {
                    "effect": 2,
                    "details": {
                        "amplifier": 1,
                        "duration": 10,
                        "ambient": False,
                        "show_particles": True,
                        "show_icon": True,
                        "hidden_effect": {
                            "amplifier": 0,
                            "duration": 5,
                            "ambient": False,
                            "show_particles": False,
                            "show_icon": False,
                            "hidden_effect": None,
                        },
                    },
                }
            ],
            "custom_name": "a",
        },
        id="potion_contents",
    ),
    pytest.param(
        53,
        "potion_contents",
        "00 00 00 00",
        {"potion": None, "custom_color": None, "custom_effects": [], "custom_name": None},
        id="potion_contents empty",
    ),
    # Consume effects: a type id and the layout of that type.
    pytest.param(
        24,
        "consumable",
        "3fc00000 01 01 01  02  00 01  01 00 c8 01 00 01 01 00  3f000000  02",
        {
            "consume_seconds": 1.5,
            "animation": 1,
            "sound": {"reference": 0},
            "has_consume_particles": True,
            "on_consume_effects": [
                {
                    "type": "minecraft:apply_effects",
                    "value": {
                        "effects": [
                            {
                                "effect": 1,
                                "details": {
                                    "amplifier": 0,
                                    "duration": 200,
                                    "ambient": False,
                                    "show_particles": True,
                                    "show_icon": True,
                                    "hidden_effect": None,
                                },
                            }
                        ],
                        "probability": 0.5,
                    },
                },
                {"type": "minecraft:clear_all_effects", "value": None},
            ],
        },
        id="consumable",
    ),
    pytest.param(
        36,
        "death_protection",
        "03  01 00 03 61 3a 62  03 40000000 01  04 01",
        [
            {"type": "minecraft:remove_effects", "value": {"tag": "a:b"}},
            {
                "type": "minecraft:teleport_randomly",
                "value": {"diameter": 2.0, "directional_particles": True},
            },
            {"type": "minecraft:play_sound", "value": {"reference": 0}},
        ],
        id="death_protection",
    ),
    # Tools, weapons and armour.
    pytest.param(
        28,
        "tool",
        "01  00 03 61 3a 62 01 40000000 01 01  3f800000 01 00",
        {
            "rules": [{"blocks": {"tag": "a:b"}, "speed": 2.0, "correct_for_drops": True}],
            "default_mining_speed": 1.0,
            "damage_per_block": 1,
            "can_destroy_blocks_in_creative": False,
        },
        id="tool",
    ),
    pytest.param(
        28,
        "tool",
        "01  01 00 00  3f800000 01 01",
        {
            "rules": [{"blocks": {"ids": []}, "speed": None, "correct_for_drops": None}],
            "default_mining_speed": 1.0,
            "damage_per_block": 1,
            "can_destroy_blocks_in_creative": True,
        },
        id="tool with a bare rule",
    ),
    pytest.param(
        32,
        "equippable",
        "03 01 01 03 61 3a 62 00 00 01 01 01 00 00 01",
        {
            "slot": 3,
            "equip_sound": {"reference": 0},
            "asset_id": "a:b",
            "camera_overlay": None,
            "allowed_entities": None,
            "dispensable": True,
            "swappable": True,
            "damage_on_hurt": True,
            "equip_on_interact": False,
            "can_be_sheared": False,
            "shearing_sound": {"reference": 0},
        },
        id="equippable",
    ),
    pytest.param(
        32,
        "equippable",
        "00 01 00 01 03 61 3a 62 01 02 07 00 00 00 01 01 01",
        {
            "slot": 0,
            "equip_sound": {"reference": 0},
            "asset_id": None,
            "camera_overlay": "a:b",
            "allowed_entities": {"ids": [7]},
            "dispensable": False,
            "swappable": False,
            "damage_on_hurt": False,
            "equip_on_interact": True,
            "can_be_sheared": True,
            "shearing_sound": {"reference": 0},
        },
        id="equippable with an overlay and allowed entities",
    ),
    pytest.param(
        37,
        "blocks_attacks",
        "3f000000 3f800000  01  42b40000 00 00000000 3f800000  3f800000 00000000 3f000000"
        "  01 00 03 61 3a 62  01 01  00",
        {
            "block_delay_seconds": 0.5,
            "disable_cooldown_scale": 1.0,
            "damage_reductions": [
                {"horizontal_blocking_angle": 90.0, "type": None, "base": 0.0, "factor": 1.0}
            ],
            "item_damage": {"threshold": 1.0, "base": 0.0, "factor": 0.5},
            "bypassed_by": {"tag": "a:b"},
            "block_sound": {"reference": 0},
            "disable_sound": None,
        },
        id="blocks_attacks",
    ),
    pytest.param(
        38,
        "piercing_weapon",
        "01 00 01 01 00",
        {
            "deals_knockback": True,
            "dismounts": False,
            "sound": {"reference": 0},
            "hit_sound": None,
        },
        id="piercing_weapon",
    ),
    pytest.param(
        39,
        "kinetic_weapon",
        "0a 05  01 14 3f800000 40000000  00  01 1e 3f000000 3f000000  3f000000 40000000  00  01 01",
        {
            "contact_cooldown_ticks": 10,
            "delay_ticks": 5,
            "dismount_conditions": {
                "max_duration_ticks": 20,
                "min_speed": 1.0,
                "min_relative_speed": 2.0,
            },
            "knockback_conditions": None,
            "damage_conditions": {
                "max_duration_ticks": 30,
                "min_speed": 0.5,
                "min_relative_speed": 0.5,
            },
            "forward_movement": 0.5,
            "damage_multiplier": 2.0,
            "sound": None,
            "hit_sound": {"reference": 0},
        },
        id="kinetic_weapon",
    ),
    pytest.param(
        57,
        "written_book_content",
        f"01 54 00  01 41  02  01 {TEXT_A} 01 {TEXT_B}  01",
        {
            "title": {"raw": "T", "filtered": None},
            "author": "A",
            "generation": 2,
            "pages": [{"raw": bytes.fromhex(TEXT_A), "filtered": bytes.fromhex(TEXT_B)}],
            "resolved": True,
        },
        id="written_book_content",
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


# Limits and refusals inside the nested types.


def test_a_consume_effect_type_id_past_the_registry_is_a_wire_error_naming_it() -> None:
    # death_protection with one effect of type 5; the registry has five (0 to 4).
    message = r"^components: added: 0: minecraft:death_protection: 0: unknown type id 5$"
    with pytest.raises(WireError, match=message):
        read_all(SLOT, stack_with_component(36, "01 05"))


def test_a_written_book_title_is_at_most_32_characters() -> None:
    title = "21" + "61" * 33  # 33 characters
    message = r"^components: added: 0: minecraft:written_book_content: title: raw: "
    with pytest.raises(WireError, match=message):
        read_all(SLOT, stack_with_component(57, f"{title} 00 01 41 00 00 01"))


def test_hidden_effects_nested_too_deeply_are_a_wire_error_not_a_crash() -> None:
    # Each level is a Details with a hidden effect after it. Python would run out of stack
    # (RecursionError) long before the 12000 bytes do; vanilla reads it on the Java stack.
    level = "00 00 00 00 00 01"
    payload = "00 00 01 00" + level * 2000 + "00 00 00 00 00 00" + "00"
    with pytest.raises(WireError, match="nested too deeply"):
        read_all(SLOT, stack_with_component(53, payload))
