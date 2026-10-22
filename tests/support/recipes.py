"""Recorded and hand-built recipe book packets, as the schema and the Comparison tests read them."""

from support.items import NO_COMPONENTS

BOOK_ADD = "minecraft:recipe_book_add"


PLANKS = {"type": "minecraft:tag", "value": {"tag": "minecraft:planks"}}


CRAFTING_TABLE = {
    "type": "minecraft:crafting_shaped",
    "value": {
        "width": 2,
        "height": 2,
        "ingredients": [PLANKS] * 4,
        "result": {
            "type": "minecraft:item_stack",
            "value": {"item": 405, "count": 1, "components": NO_COMPONENTS},
        },
        "crafting_station": {"type": "minecraft:item", "value": 405},
    },
}


ITEM_7 = {"type": "minecraft:item", "value": 7}


RECIPE_DISPLAYS = {
    "crafting_shapeless": (
        {
            "type": "minecraft:crafting_shapeless",
            "value": {"ingredients": [ITEM_7], "result": ITEM_7, "crafting_station": ITEM_7},
        },
        b"\x00\x01\x04\x07\x04\x07\x04\x07",
    ),
    "furnace": (
        {
            "type": "minecraft:furnace",
            "value": {
                "ingredient": ITEM_7,
                "fuel": {"type": "minecraft:any_fuel", "value": None},
                "result": ITEM_7,
                "crafting_station": ITEM_7,
                "duration": 200,
                "experience": 0.5,
            },
        },
        b"\x02\x04\x07\x01\x04\x07\x04\x07\xc8\x01\x3f\x00\x00\x00",
    ),
    "stonecutter": (
        {
            "type": "minecraft:stonecutter",
            "value": {"input": ITEM_7, "result": ITEM_7, "crafting_station": ITEM_7},
        },
        b"\x03\x04\x07\x04\x07\x04\x07",
    ),
    "smithing": (
        {
            "type": "minecraft:smithing",
            "value": {
                "template": ITEM_7,
                "base": ITEM_7,
                "addition": ITEM_7,
                "result": ITEM_7,
                "crafting_station": ITEM_7,
            },
        },
        b"\x04" + b"\x04\x07" * 5,
    ),
}
