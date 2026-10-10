"""Play-state schemas for recipes: what a joining player gets in `update_recipes`.

Field layouts: minecraft.wiki `Java_Edition_protocol/Packets`, revision 3790659 (2026-09-23,
"26.3, protocol 777"), "Update Recipes", and `Java_Edition_protocol/Recipes`, revision
3661933 (2026-07-07), "Slot Display", raw wikitext. Checked against the 26.3 client jar with
`javap`, which wins where the wiki is older (#106):

- `ClientboundUpdateRecipesPacket.STREAM_CODEC`: `ByteBufCodecs.map(HashMap::new,
  ResourceKey.streamCodec(RecipePropertySet.TYPE_KEY), RecipePropertySet.STREAM_CODEC)`, then
  `SelectableRecipe$SingleInputSet.noRecipeCodec()`. `RecipePropertySet.STREAM_CODEC` is a list
  of `Item.STREAM_CODEC` (`ByteBufCodecs.holderRegistry`: a registry id), read into
  `Set.copyOf`. A stonecutter entry is `Ingredient.CONTENTS_STREAM_CODEC`
  (`ByteBufCodecs.holderSet`) and the recipe's `SlotDisplay`.
- `SlotDisplay.STREAM_CODEC` is `ByteBufCodecs.registry(SLOT_DISPLAY).dispatch`, the types in
  `SlotDisplays.bootstrap`'s order. Unlike the wiki: `item_stack` is an `ItemStackTemplate`, not
  a Slot; `tag` is a holder set (`ByteBufCodecs.holderSet(ITEM)`), not an Identifier; and
  `smithing_trim`'s pattern is `TrimPattern.STREAM_CODEC` (`ByteBufCodecs.holder`), a registry
  id or the pattern itself.
"""

from collections.abc import Mapping

from mscts.codec.components import ITEM_STACK_TEMPLATE
from mscts.codec.entity_data import OPTIONAL_UNSIGNED_INT
from mscts.codec.registry_names import registry_names
from mscts.codec.schema import (
    BOOL,
    BYTE,
    FLOAT,
    IDENTIFIER,
    VAR_INT,
    PrefixedArray,
    PrefixedOptional,
    Schema,
)
from mscts.codec.shapes import (
    HOLDER_SET,
    REGISTRY_ID,
    TEXT_COMPONENT,
    Deferred,
    Holder,
    registry_dispatch,
)
from mscts.target import TARGET

_SLOT_DISPLAY_INSIDE = Deferred(lambda: _SLOT_DISPLAY)
"""A slot display inside another (`StreamCodec.recursive` in vanilla's terms)."""

_TRIM_PATTERN = Holder(Schema(asset_id=IDENTIFIER, description=TEXT_COMPONENT, decal=BOOL))
"""`TrimPattern.STREAM_CODEC`: a registry id, or the asset id, description and decal flag."""

# A slot display: the id of its type in `minecraft:slot_display`, then that type's data. A type
# of one field is that field's value, with no wrapper.
_SLOT_DISPLAY = registry_dispatch(
    registry_names(TARGET.minecraft_version, "minecraft:slot_display"),
    {
        "minecraft:empty": None,
        "minecraft:any_fuel": None,
        "minecraft:with_any_potion": _SLOT_DISPLAY_INSIDE,
        "minecraft:only_with_component": Schema(
            base=_SLOT_DISPLAY_INSIDE, component_type=REGISTRY_ID
        ),
        "minecraft:item": REGISTRY_ID,
        "minecraft:item_stack": ITEM_STACK_TEMPLATE,
        "minecraft:tag": HOLDER_SET,
        "minecraft:dyed": Schema(dye=_SLOT_DISPLAY_INSIDE, target=_SLOT_DISPLAY_INSIDE),
        "minecraft:smithing_trim": Schema(
            base=_SLOT_DISPLAY_INSIDE, material=_SLOT_DISPLAY_INSIDE, pattern=_TRIM_PATTERN
        ),
        "minecraft:with_remainder": Schema(
            ingredient=_SLOT_DISPLAY_INSIDE, remainder=_SLOT_DISPLAY_INSIDE
        ),
        "minecraft:composite": PrefixedArray(_SLOT_DISPLAY_INSIDE),
    },
)

_RECIPE_DISPLAY = registry_dispatch(
    registry_names(TARGET.minecraft_version, "minecraft:recipe_display"),
    {
        "minecraft:crafting_shapeless": Schema(
            ingredients=PrefixedArray(_SLOT_DISPLAY),
            result=_SLOT_DISPLAY,
            crafting_station=_SLOT_DISPLAY,
        ),
        "minecraft:crafting_shaped": Schema(
            width=VAR_INT,
            height=VAR_INT,
            ingredients=PrefixedArray(_SLOT_DISPLAY),
            result=_SLOT_DISPLAY,
            crafting_station=_SLOT_DISPLAY,
        ),
        "minecraft:furnace": Schema(
            ingredient=_SLOT_DISPLAY,
            fuel=_SLOT_DISPLAY,
            result=_SLOT_DISPLAY,
            crafting_station=_SLOT_DISPLAY,
            duration=VAR_INT,
            experience=FLOAT,
        ),
        "minecraft:stonecutter": Schema(
            input=_SLOT_DISPLAY, result=_SLOT_DISPLAY, crafting_station=_SLOT_DISPLAY
        ),
        "minecraft:smithing": Schema(
            template=_SLOT_DISPLAY,
            base=_SLOT_DISPLAY,
            addition=_SLOT_DISPLAY,
            result=_SLOT_DISPLAY,
            crafting_station=_SLOT_DISPLAY,
        ),
    },
)
"""How the recipe book shows a recipe: the id of its type in `minecraft:recipe_display`, then
that type's slots (and a furnace's time and experience)."""

_RECIPE_DISPLAY_ENTRY = Schema(
    id=VAR_INT,
    display=_RECIPE_DISPLAY,
    group=OPTIONAL_UNSIGNED_INT,
    category=REGISTRY_ID,
    crafting_requirements=PrefixedOptional(PrefixedArray(HOLDER_SET)),
)
"""`RecipeDisplayEntry`: the display id the client names the recipe by, its display, the group
it is shown with (an id plus one, 0 for none), its `minecraft:recipe_book_category`, and the
items each ingredient takes, if the book checks them."""

SERVERBOUND: Mapping[str, Schema] = {
    # Place Recipe: the window, the recipe's display id, and whether to fill the grid with as
    # many sets as the inventory holds (shift-click in the book).
    "minecraft:place_recipe": Schema(window_id=VAR_INT, recipe_id=VAR_INT, use_max_items=BOOL),
}

CLIENTBOUND: Mapping[str, Schema] = {
    # Recipe Book Add: each recipe added, with its flags (1 shows a toast, 2 highlights it),
    # then whether the book is cleared first.
    "minecraft:recipe_book_add": Schema(
        entries=PrefixedArray(Schema(contents=_RECIPE_DISPLAY_ENTRY, flags=BYTE)),
        replace=BOOL,
    ),
    # Recipe Book Remove: the display ids of the recipes taken from the book.
    "minecraft:recipe_book_remove": Schema(recipes=PrefixedArray(VAR_INT)),
    # Place Ghost Recipe: the window, and the recipe the grid shows as ghost items.
    "minecraft:place_ghost_recipe": Schema(window_id=VAR_INT, recipe_display=_RECIPE_DISPLAY),
    # Update Recipes: the item sets that recipes take as input (the furnace's, the smithing
    # table's, ...), each a property set id and item registry ids; then each stonecutter
    # recipe's ingredients and what its button shows.
    "minecraft:update_recipes": Schema(
        property_sets=PrefixedArray(
            Schema(property_set_id=IDENTIFIER, items=PrefixedArray(REGISTRY_ID))
        ),
        stonecutter_recipes=PrefixedArray(
            Schema(ingredients=HOLDER_SET, slot_display=_SLOT_DISPLAY)
        ),
    ),
}
