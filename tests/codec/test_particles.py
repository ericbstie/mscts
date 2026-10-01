"""Particles: each type's id and options, pinned with `javap` on the 26.3 server jar.

The hex payloads are built by hand from the option layouts (a VarInt type id, then the
options), not produced by the Codec.
"""

import pytest

from mscts.codec.particles import PARTICLE, POSITION_SOURCE
from mscts.codec.schema import EntityId, Schema, WireType
from mscts.codec.wire import Reader, WireError, Writer

PARTICLE_NAMES = (
    "minecraft:angry_villager",
    "minecraft:block",
    "minecraft:block_marker",
    "minecraft:bubble",
    "minecraft:sulfur_bubbles",
    "minecraft:noxious_gas",
    "minecraft:noxious_gas_cloud",
    "minecraft:geyser",
    "minecraft:geyser_base",
    "minecraft:geyser_poof",
    "minecraft:geyser_plume",
    "minecraft:cloud",
    "minecraft:copper_fire_flame",
    "minecraft:crit",
    "minecraft:damage_indicator",
    "minecraft:dragon_breath",
    "minecraft:dripping_lava",
    "minecraft:falling_lava",
    "minecraft:landing_lava",
    "minecraft:dripping_water",
    "minecraft:falling_water",
    "minecraft:dust",
    "minecraft:dust_color_transition",
    "minecraft:effect",
    "minecraft:elder_guardian",
    "minecraft:enchanted_hit",
    "minecraft:enchant",
    "minecraft:end_rod",
    "minecraft:entity_effect",
    "minecraft:explosion_emitter",
    "minecraft:explosion",
    "minecraft:gust",
    "minecraft:small_gust",
    "minecraft:gust_emitter_large",
    "minecraft:gust_emitter_small",
    "minecraft:sonic_boom",
    "minecraft:falling_dust",
    "minecraft:firework",
    "minecraft:fishing",
    "minecraft:flame",
    "minecraft:infested",
    "minecraft:cherry_leaves",
    "minecraft:pale_oak_leaves",
    "minecraft:red_poplar_leaves",
    "minecraft:orange_poplar_leaves",
    "minecraft:yellow_poplar_leaves",
    "minecraft:tinted_leaves",
    "minecraft:sculk_soul",
    "minecraft:sculk_charge",
    "minecraft:sculk_charge_pop",
    "minecraft:soul_fire_flame",
    "minecraft:soul",
    "minecraft:flash",
    "minecraft:happy_villager",
    "minecraft:composter",
    "minecraft:heart",
    "minecraft:instant_effect",
    "minecraft:item",
    "minecraft:vibration",
    "minecraft:trail",
    "minecraft:pause_mob_growth",
    "minecraft:reset_mob_growth",
    "minecraft:item_slime",
    "minecraft:item_cobweb",
    "minecraft:item_snowball",
    "minecraft:large_smoke",
    "minecraft:lava",
    "minecraft:mycelium",
    "minecraft:note",
    "minecraft:poof",
    "minecraft:portal",
    "minecraft:rain",
    "minecraft:smoke",
    "minecraft:white_smoke",
    "minecraft:sneeze",
    "minecraft:spit",
    "minecraft:squid_ink",
    "minecraft:sweep_attack",
    "minecraft:totem_of_undying",
    "minecraft:underwater",
    "minecraft:splash",
    "minecraft:witch",
    "minecraft:bubble_pop",
    "minecraft:current_down",
    "minecraft:bubble_column_up",
    "minecraft:nautilus",
    "minecraft:dolphin",
    "minecraft:campfire_cosy_smoke",
    "minecraft:campfire_signal_smoke",
    "minecraft:dripping_honey",
    "minecraft:falling_honey",
    "minecraft:landing_honey",
    "minecraft:falling_nectar",
    "minecraft:falling_spore_blossom",
    "minecraft:ash",
    "minecraft:crimson_spore",
    "minecraft:warped_spore",
    "minecraft:spore_blossom_air",
    "minecraft:dripping_obsidian_tear",
    "minecraft:falling_obsidian_tear",
    "minecraft:landing_obsidian_tear",
    "minecraft:reverse_portal",
    "minecraft:white_ash",
    "minecraft:small_flame",
    "minecraft:snowflake",
    "minecraft:dripping_dripstone_lava",
    "minecraft:falling_dripstone_lava",
    "minecraft:dripping_dripstone_water",
    "minecraft:falling_dripstone_water",
    "minecraft:glow_squid_ink",
    "minecraft:glow",
    "minecraft:wax_on",
    "minecraft:wax_off",
    "minecraft:electric_spark",
    "minecraft:scrape",
    "minecraft:shriek",
    "minecraft:egg_crack",
    "minecraft:dust_plume",
    "minecraft:trial_spawner_detection",
    "minecraft:trial_spawner_detection_ominous",
    "minecraft:vault_connection",
    "minecraft:dust_pillar",
    "minecraft:ominous_spawning",
    "minecraft:raid_omen",
    "minecraft:trial_omen",
    "minecraft:block_crumble",
    "minecraft:firefly",
    "minecraft:sulfur_cube_goo",
)

WITH_OPTIONS = {
    "block",
    "block_marker",
    "geyser",
    "geyser_base",
    "geyser_poof",
    "geyser_plume",
    "dragon_breath",
    "dust",
    "dust_color_transition",
    "effect",
    "entity_effect",
    "falling_dust",
    "tinted_leaves",
    "sculk_charge",
    "flash",
    "instant_effect",
    "item",
    "vibration",
    "trail",
    "shriek",
    "dust_pillar",
    "block_crumble",
}


def written[T](wire_type: WireType[T], value: object) -> bytes:
    writer = Writer()
    wire_type.write(writer, value)
    return writer.to_bytes()


def read_all[T](wire_type: WireType[T], data: bytes) -> T:
    reader = Reader(data)
    value = wire_type.read(reader)
    reader.expect_end()
    return value


def particle(name: str, options: object = None) -> dict[str, object]:
    return {"type": f"minecraft:{name}", "options": options}


def test_the_particle_registry_is_in_the_order_of_26_3() -> None:
    assert len(PARTICLE_NAMES) == 128
    assert PARTICLE.names == PARTICLE_NAMES
    assert PARTICLE.names.index("minecraft:block") == 1
    assert PARTICLE.names.index("minecraft:dust") == 21
    assert PARTICLE.names.index("minecraft:item") == 57
    assert PARTICLE.names.index("minecraft:shriek") == 115
    assert PARTICLE.names.index("minecraft:sulfur_cube_goo") == 127


@pytest.mark.parametrize(
    "type_id",
    [
        number
        for number, name in enumerate(PARTICLE_NAMES)
        if name.removeprefix("minecraft:") not in WITH_OPTIONS
    ],
)
def test_a_particle_with_no_options_is_just_its_id(type_id: int) -> None:
    value = read_all(PARTICLE, bytes([type_id]))
    assert value == {"type": PARTICLE_NAMES[type_id], "options": None}
    assert written(PARTICLE, value) == bytes([type_id])


# Each sample: the type, its hex (id then options), the decoded options.
SAMPLES = [
    ("block", "01ac02", {"block_state": 300}),
    ("block_marker", "0201", {"block_state": 1}),
    ("geyser", "0700000005", {"water_blocks": 5}),
    ("geyser_base", "08000000033f000000", {"water_blocks": 3, "burst_impulse_base": 0.5}),
    ("geyser_poof", "0900000000bf800000", {"water_blocks": 0, "burst_impulse_base": -1.0}),
    ("geyser_plume", "0a000000ff", {"water_blocks": 255}),
    ("dragon_breath", "0f3f800000", {"power": 1.0}),
    ("dust", "1500ff00003f800000", {"color": 16711680, "scale": 1.0}),
    (
        "dust_color_transition",
        "1600ff0000000000ff40000000",
        {"from_color": 16711680, "to_color": 255, "scale": 2.0},
    ),
    ("effect", "17ffffffff3e800000", {"color": -1, "power": 0.25}),
    ("entity_effect", "1cffaabbcc", {"color": -5588020}),
    ("falling_dust", "240a", {"block_state": 10}),
    ("tinted_leaves", "2e80000001", {"color": -2147483647}),
    ("sculk_charge", "303fc00000", {"roll": 1.5}),
    ("flash", "3401020304", {"color": 16909060}),
    ("instant_effect", "380000000141200000", {"color": 1, "power": 10.0}),
    (
        "vibration",
        "3a00000000400000300214",
        {
            "destination": {"type": "minecraft:block", "value": {"x": 1, "y": 2, "z": 3}},
            "arrival_in_ticks": 20,
        },
    ),
    (
        "vibration",
        "3a012a3f00000078",
        {
            "destination": {
                "type": "minecraft:entity",
                "value": {"entity_id": 42, "y_offset": 0.5},
            },
            "arrival_in_ticks": 120,
        },
    ),
    (
        "trail",
        "3b3ff80000000000004050000000000000c00400000000000000ff00ffc801",
        {"target": {"x": 1.5, "y": 64.0, "z": -2.5}, "color": 16711935, "duration": 200},
    ),
    ("shriek", "7305", {"delay": 5}),
    ("dust_pillar", "790a", {"block_state": 10}),
    ("block_crumble", "7d0a", {"block_state": 10}),
    # The item particle holds a stack template: the item, then the count (not a slot's order),
    # then the components.
    (
        "item",
        "39 37 01 00 00",
        {"item": 55, "count": 1, "components": {"added": [], "removed": []}},
    ),
    (
        "item",
        "39 37 02 01 00 03 07",
        {
            "item": 55,
            "count": 2,
            "components": {"added": [{"type": "minecraft:damage", "value": 7}], "removed": []},
        },
    ),
]


@pytest.mark.parametrize(("name", "encoded", "options"), SAMPLES)
def test_a_particle_with_options_decodes_them_and_encodes_the_same_bytes(
    name: str, encoded: str, options: dict[str, object]
) -> None:
    assert read_all(PARTICLE, bytes.fromhex(encoded)) == particle(name, options)
    assert written(PARTICLE, particle(name, options)) == bytes.fromhex(encoded)


def test_every_type_that_has_options_is_sampled_and_no_other_is() -> None:
    assert {name for name, _, _ in SAMPLES} == WITH_OPTIONS


def test_the_item_particle_is_not_a_slot() -> None:
    # `39 01 37 00 00` is a slot of one of item 55, and a template of 55 of item 1.
    value = read_all(PARTICLE, bytes.fromhex("39 01 37 00 00"))
    assert value == particle(
        "item", {"item": 1, "count": 55, "components": {"added": [], "removed": []}}
    )


def test_the_item_particle_refuses_a_component_it_cannot_read() -> None:
    with pytest.raises(
        WireError,
        match=r"^minecraft:item: components: added: 0: unknown data component type id 122$",
    ):
        read_all(PARTICLE, bytes.fromhex("39 37 01 01 00 7a"))


def test_a_particle_type_id_past_the_registry_is_refused() -> None:
    with pytest.raises(WireError, match=r"^unknown type id 128$"):
        read_all(PARTICLE, bytes.fromhex("8001"))


@pytest.mark.parametrize(
    ("encoded", "error"),
    [
        ("0700", r"^minecraft:geyser: water_blocks: int truncated"),
        ("3a0000000040", r"^minecraft:vibration: destination: minecraft:block: long truncated"),
        ("3a02", r"^minecraft:vibration: destination: unknown type id 2$"),
        ("3a012a3f0000", r"^minecraft:vibration: destination: minecraft:entity: y_offset: "),
        ("3a012a3f000000", r"^minecraft:vibration: arrival_in_ticks: VarInt truncated$"),
    ],
)
def test_a_particle_refuses_bad_options(encoded: str, error: str) -> None:
    with pytest.raises(WireError, match=error):
        read_all(PARTICLE, bytes.fromhex(encoded))


def test_a_particle_refuses_options_a_type_does_not_take() -> None:
    with pytest.raises(WireError, match=r"^minecraft:bubble: takes no options$"):
        written(PARTICLE, particle("bubble", {"x": 1}))


def test_a_particle_with_options_refuses_none() -> None:
    with pytest.raises(WireError, match=r"^minecraft:dust: expected a mapping"):
        written(PARTICLE, particle("dust"))


@pytest.mark.parametrize(
    ("value", "encoded"),
    [
        ({"type": "minecraft:block", "value": {"x": -1, "y": -1, "z": -1}}, "00ffffffffffffffff"),
        (
            {"type": "minecraft:entity", "value": {"entity_id": 300, "y_offset": -1.0}},
            "01ac02bf800000",
        ),
    ],
)
def test_a_position_source_is_a_block_position_or_an_entity(
    value: dict[str, object], encoded: str
) -> None:
    assert written(POSITION_SOURCE, value) == bytes.fromhex(encoded)
    assert read_all(POSITION_SOURCE, bytes.fromhex(encoded)) == value


def test_the_entity_a_position_source_follows_is_an_entity_id_type() -> None:
    entity = dict(POSITION_SOURCE.variants)["minecraft:entity"]
    assert isinstance(entity, Schema)
    assert isinstance(entity.fields["entity_id"], EntityId)


def test_a_position_source_refuses_a_kind_the_registry_lacks() -> None:
    with pytest.raises(WireError, match=r"^unknown type id 2$"):
        read_all(POSITION_SOURCE, b"\x02")
