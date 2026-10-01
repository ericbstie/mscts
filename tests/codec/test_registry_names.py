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


def test_consume_effect_names_are_the_registry_in_protocol_id_order() -> None:
    assert registry_names(TARGET.minecraft_version, "minecraft:consume_effect_type") == (
        "minecraft:apply_effects",
        "minecraft:remove_effects",
        "minecraft:clear_all_effects",
        "minecraft:teleport_randomly",
        "minecraft:play_sound",
    )
