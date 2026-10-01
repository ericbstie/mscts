from mscts.codec.registry_names import registry_names
from mscts.target import TARGET

# These ids are the 26.3 server jar's `minecraft:data_component_type` protocol ids, from
# reports/registries.json (docs/research/2026-09-30-item-stacks.md).


def test_data_component_names_are_the_registry_in_protocol_id_order() -> None:
    names = registry_names(TARGET.minecraft_version, "minecraft:data_component_type")
    assert len(names) == 122
    assert names[0] == "minecraft:custom_data"
    assert names[3] == "minecraft:damage"
    assert names[6] == "minecraft:custom_name"
    assert names[11] == "minecraft:lore"
    assert names[13] == "minecraft:enchantments"
    assert names[121] == "minecraft:cushion/color"
    assert len(set(names)) == len(names)


def test_command_argument_type_names_are_the_registry_in_protocol_id_order() -> None:
    # The Brigadier argument parsers of the `commands` packet (#17), by protocol id: 0 to 11
    # are the parsers the wiki's command data page numbers the same way.
    names = registry_names(TARGET.minecraft_version, "minecraft:command_argument_type")
    assert len(names) == 62
    assert names[:12] == (
        "brigadier:bool",
        "brigadier:float",
        "brigadier:double",
        "brigadier:integer",
        "brigadier:long",
        "brigadier:string",
        "minecraft:entity",
        "minecraft:game_profile",
        "minecraft:block_pos",
        "minecraft:column_pos",
        "minecraft:vec3",
        "minecraft:vec2",
    )
    assert names[61] == "minecraft:uuid"
    assert len(set(names)) == len(names)


def test_consume_effect_names_are_the_registry_in_protocol_id_order() -> None:
    assert registry_names(TARGET.minecraft_version, "minecraft:consume_effect_type") == (
        "minecraft:apply_effects",
        "minecraft:remove_effects",
        "minecraft:clear_all_effects",
        "minecraft:teleport_randomly",
        "minecraft:play_sound",
    )
