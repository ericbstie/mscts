from mscts.codec.registry_names import block_state_count, registry_names
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


def test_entity_type_names_are_the_registry_in_protocol_id_order() -> None:
    # An add_entity's `type` (#21): vanilla sent 159 for a player and 101 for a pig.
    names = registry_names(TARGET.minecraft_version, "minecraft:entity_type")
    assert names[159] == "minecraft:player"
    assert names[101] == "minecraft:pig"
    assert len(set(names)) == len(names)


def test_slot_display_names_are_the_registry_in_protocol_id_order() -> None:
    # A recipe's slot display (#106), in `SlotDisplays.bootstrap`'s registration order.
    assert registry_names(TARGET.minecraft_version, "minecraft:slot_display") == (
        "minecraft:empty",
        "minecraft:any_fuel",
        "minecraft:with_any_potion",
        "minecraft:only_with_component",
        "minecraft:item",
        "minecraft:item_stack",
        "minecraft:tag",
        "minecraft:dyed",
        "minecraft:smithing_trim",
        "minecraft:with_remainder",
        "minecraft:composite",
    )


def test_block_state_count_is_the_states_of_the_block_report() -> None:
    # 26.3's blocks.json: 35,723 states, ids 0 to 35,722, so a direct block container has
    # 16 bits per entry (docs/research/2026-10-02-chunks-light.md).
    assert block_state_count(TARGET.minecraft_version) == 35_723


def test_consume_effect_names_are_the_registry_in_protocol_id_order() -> None:
    assert registry_names(TARGET.minecraft_version, "minecraft:consume_effect_type") == (
        "minecraft:apply_effects",
        "minecraft:remove_effects",
        "minecraft:clear_all_effects",
        "minecraft:teleport_randomly",
        "minecraft:play_sound",
    )


def test_item_names_are_the_registry_in_protocol_id_order() -> None:
    # A stack's `item` (#28): the reference tier saw stone as 1 and a diamond sword as 1050.
    names = registry_names(TARGET.minecraft_version, "minecraft:item")
    assert len(names) == 1658
    assert names[0] == "minecraft:air"
    assert names[1] == "minecraft:stone"
    assert names[1050] == "minecraft:diamond_sword"
    assert len(set(names)) == len(names)


def test_menu_names_are_the_registry_in_protocol_id_order() -> None:
    # An open_screen's `window_type` (#28): a single chest opened as 2.
    names = registry_names(TARGET.minecraft_version, "minecraft:menu")
    assert names[:7] == (
        "minecraft:generic_9x1",
        "minecraft:generic_9x2",
        "minecraft:generic_9x3",
        "minecraft:generic_9x4",
        "minecraft:generic_9x5",
        "minecraft:generic_9x6",
        "minecraft:generic_3x3",
    )
    assert names[16] == "minecraft:hopper"
    assert names[20] == "minecraft:shulker_box"
    assert len(names) == 25
