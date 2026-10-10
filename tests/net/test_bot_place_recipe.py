"""`Bot.place_recipe`: a click on a recipe in the recipe book, as the 26.3 client reports it.

`RecipeBookComponent.tryPlaceRecipe` calls `MultiPlayerGameMode.handlePlaceRecipe` with the
open menu's container id, which sends `place_recipe` at once, outside any tick; the client
changes no slot itself: the server fills the grid (javap).
"""

import pytest

from mscts.bot import Bot
from mscts.net import ProtocolError
from mscts.transcript import Transcript
from tests.net.fakes import status_server, with_bot
from tests.net.test_bot_inventory import CHEST, GENERIC_9X3, inventory_after, open_screen
from tests.net.test_bot_move import CODEC

CRAFTING_TABLE = 339
"""The crafting table's display id in a fresh vanilla 26.3 Instance's recipe book."""


@pytest.mark.parametrize("use_max_items", [False, True], ids=["once", "as-many-as-possible"])
def test_place_recipe_sends_the_open_windows_id_the_recipe_and_whether_to_use_the_most(
    use_max_items: bool,  # noqa: FBT001
) -> None:
    async def script(bot: Bot) -> None:
        await bot.place_recipe(CRAFTING_TABLE, use_max_items=use_max_items)

    view, sent = inventory_after([open_screen(CHEST, GENERIC_9X3)], script)
    fields = {"window_id": CHEST, "recipe_id": CRAFTING_TABLE, "use_max_items": use_max_items}
    assert sent == [("minecraft:place_recipe", fields)]
    assert view.window_id == CHEST


def test_place_recipe_with_no_container_open_names_the_inventory_window() -> None:
    async def script(bot: Bot) -> None:
        await bot.place_recipe(CRAFTING_TABLE)

    _, sent = inventory_after([], script)
    assert sent == [
        (
            "minecraft:place_recipe",
            {"window_id": 0, "recipe_id": CRAFTING_TABLE, "use_max_items": False},
        )
    ]


def test_place_recipe_refuses_a_bot_that_is_not_in_play() -> None:
    transcript = Transcript(group_id="test/place-recipe", server="fake")

    async def use(bot: Bot) -> None:
        with pytest.raises(
            ProtocolError, match="place_recipe needs a Bot in play, not one in handshake"
        ):
            await bot.place_recipe(CRAFTING_TABLE)

    with_bot(CODEC, transcript, status_server("{}", []), use)
    assert transcript.events == []
