"""The crafting Groups: what each Bot sends in each window, Control's setup, and the undo.

Every test plays a Group against a fake server and reads the Transcript for what the Bots sent
(the clicks, the recipe placements, Control's commands) and the Marks (the Observation windows).
What a server answers is never asserted: the fake answers the barrier and Control's markers, and
does what the Bot needs to act as it would against vanilla: an item replaced or cleared shows in
the Bot's inventory, a recipe given is added to its book with a display id, and a use on a block
opens a crafting table.
"""

import asyncio
import functools
import json
from contextlib import suppress
from dataclasses import dataclass, field

import pytest

from mscts.bot import SYNC_REQUESTS
from mscts.codec.packets import Direction, Packet
from mscts.codec.registry_names import registry_names
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN
from mscts.group import GROUPS, GroupContext, GroupKind
from mscts.groups import crafting
from mscts.spec import ServerSpec
from mscts.target import TARGET
from mscts.transcript import Transcript
from tests.group.test_control import CODEC, chat, tree
from tests.net.fakes import NO_STATISTICS, TICK_S, JoinScript, Peer, join_server, serve

CONTROL = "control"
CHAT_COMMAND, CLIENT_COMMAND = "minecraft:chat_command", "minecraft:client_command"
CLICK, PLACE_RECIPE = "minecraft:container_click", "minecraft:place_recipe"
USE_ITEM_ON = "minecraft:use_item_on"
MARKER = "tellraw @s "
COMMANDS = tree(
    "gamerule", "tp", "clear", "item", "recipe", "setblock", "advancement", "give", "tellraw"
)
PLAY_TIMEOUT_S = 300.0
GRID = "crafting/grid"
GROUP_IDS = (GRID,)
INVENTORY_SLOTS = 46
"""The inventory menu's slots: result, the 2x2, the armor, the 27, the hotbar, the off hand."""
TABLE_WINDOW = 1
"""The window id the fake gives the crafting table it opens."""
_ITEMS = registry_names(TARGET.minecraft_version, "minecraft:item")
_MENUS = registry_names(TARGET.minecraft_version, "minecraft:menu")
_DISPLAY = {
    "type": "minecraft:crafting_shapeless",
    "value": {
        "ingredients": [{"type": "minecraft:item", "value": 1}],
        "result": {"type": "minecraft:item", "value": 1},
        "crafting_station": {"type": "minecraft:item", "value": 1},
    },
}


def display_id(recipe: str) -> int:
    """The display id the fake gives `recipe`: one of its own, unlike vanilla's."""
    return 1000 + sum(recipe.encode())


def menu_slot(slot: str) -> int:
    """The inventory menu's slot for an `item replace` slot name: `hotbar.N` or `inventory.N`."""
    kind, number = slot.split(".")
    return {"hotbar": 36, "inventory": 9}[kind] + int(number)


@dataclass
class CraftingServer:
    """A fake server that joins like vanilla and does what these Groups' commands change.

    It answers the barrier (a tick apart) and Control's markers, as vanilla does, and:
    `item replace entity <bot> <slot> with <item> <count>` sets that slot of the Bot's inventory
    menu, `clear <bot>` empties it, `recipe give <bot> <recipe>` adds the recipe to the Bot's
    book with `display_id`, and a Bot's `use_item_on` opens a crafting table as window 1. Every
    serverbound Packet goes into `seen`.
    """

    seen: list[Packet] = field(default_factory=list)
    _peers: dict[str, Peer] = field(default_factory=dict, init=False)

    async def __call__(self, peer: Peer) -> None:
        """Serve one connection: a Handler."""
        # A Bot that leaves with something unread resets the connection instead of closing it.
        with suppress(ConnectionError):
            await join_server(self.seen, JoinScript(commands=COMMANDS, then=self._play))(peer)

    async def _play(self, peer: Peer) -> None:
        self._peers[peer.name] = peer
        requests = 0
        async for packet in peer.packets():
            self.seen.append(packet)
            if packet.name == CLIENT_COMMAND:
                requests += 1
                if (requests - 1) % SYNC_REQUESTS != 0:
                    await asyncio.sleep(TICK_S)  # a barrier's answers come a tick apart
                await peer.write(peer.raw_frame("minecraft:award_stats", NO_STATISTICS))
            elif packet.name == CHAT_COMMAND:
                await self._command(peer, str((packet.fields or {})["command"]))
            elif packet.name == USE_ITEM_ON:
                await peer.send(
                    "minecraft:open_screen",
                    window_id=TABLE_WINDOW,
                    window_type=_MENUS.index("minecraft:crafting"),
                    window_title=b"\x08\x00\x08Crafting",
                )

    async def _command(self, peer: Peer, command: str) -> None:
        """Answer a marker; do what any other command changes for a Bot first."""
        if command.startswith(MARKER):
            await peer.write(chat(peer, json.loads(command.removeprefix(MARKER))))
            return
        words = command.split()
        target = self._peers.get(words[1]) if len(words) > 1 else None
        if target is None:
            target = self._peers.get(words[3]) if len(words) > 3 else None
        if target is not None:
            frame = self._effect(target, words)
            if frame is not None:
                await target.write(frame)

    def _effect(self, target: Peer, words: list[str]) -> bytes | None:
        """The frame a command sends the Bot it names, if it sends one."""
        match words:
            case ["item", "replace", "entity", _, slot, "with", item, count]:
                stack = {"item": _ITEMS.index(item), "count": int(count)}
                stack["components"] = {"added": [], "removed": []}
                return target.frame(
                    "minecraft:container_set_slot",
                    window_id=0,
                    state_id=1,
                    slot=menu_slot(slot),
                    slot_data=stack,
                )
            case ["clear", _]:
                return target.frame(
                    "minecraft:container_set_content",
                    window_id=0,
                    state_id=1,
                    slot_data=[None] * INVENTORY_SLOTS,
                    carried_item=None,
                )
            case ["recipe", "give", _, recipe] if recipe != "*":
                contents = {
                    "id": display_id(recipe),
                    "display": _DISPLAY,
                    "group": None,
                    "category": 0,
                    "crafting_requirements": None,
                }
                entries = [{"contents": contents, "flags": 3}]
                return target.frame("minecraft:recipe_book_add", entries=entries, replace=False)
            case _:
                return None


@dataclass(frozen=True)
class Window:
    """One Observation window: Control's commands before and inside it, and the Bot's actions.

    `sent` holds the clicks and recipe placements the Bot sent inside the window, as
    (name, fields).
    """

    label: str
    before: tuple[str, ...]
    control: tuple[str, ...]
    sent: tuple[tuple[str, dict[str, object]], ...]


@dataclass(frozen=True)
class Play:
    """A played Group: its windows, Control's commands, and those after the last window."""

    windows: tuple[Window, ...]
    commands: tuple[str, ...]
    after: tuple[str, ...]
    opened_table_before: int | None
    """The index of the first window that the Bot's use of the table came before, if any."""


def _commands(transcript: Transcript) -> list[tuple[int, str]]:
    """Control's commands with when, but its markers."""
    return [
        (event.t_ns, str((event.packet.fields or {})["command"]))
        for event in transcript.events
        if event.bot == CONTROL
        and event.packet.direction is Direction.SERVERBOUND
        and event.packet.name == CHAT_COMMAND
        and not str((event.packet.fields or {})["command"]).startswith(MARKER)
    ]


def read(transcript: Transcript, bot: str) -> Play:
    """The windows of `transcript`, each from its open Mark to its close Mark."""
    opens = [(m.t_ns, m.label) for m in transcript.marks if m.label.startswith(OBSERVE_OPEN)]
    closes = [m.t_ns for m in transcript.marks if m.label == OBSERVE_CLOSE]
    assert len(opens) == len(closes), transcript.marks
    actions = [
        (event.t_ns, event.packet.name, dict(event.packet.fields or {}))
        for event in transcript.events
        if event.bot == bot
        and event.packet.direction is Direction.SERVERBOUND
        and event.packet.name in {CLICK, PLACE_RECIPE, USE_ITEM_ON}
    ]
    commands = _commands(transcript)
    windows, previous = [], 0
    for (opened, label), closed in zip(opens, closes, strict=True):
        windows.append(
            Window(
                label=label,
                before=tuple(c for t, c in commands if previous <= t < opened),
                control=tuple(c for t, c in commands if opened <= t <= closed),
                sent=tuple((n, f) for t, n, f in actions if opened <= t <= closed),
            )
        )
        previous = closed
    uses = [t for t, name, _ in actions if name == USE_ITEM_ON]
    first_after = None
    if uses:
        first_after = next(i for i, (opened, _) in enumerate(opens) if opened > uses[0])
    return Play(
        tuple(windows),
        tuple(c for _, c in commands),
        tuple(c for t, c in commands if t > previous),
        first_after,
    )


BOTS = {GRID: crafting.CRAFTER}


async def _play(group_id: str) -> Play:
    transcript = Transcript(group_id=group_id, server="fake")
    async with serve(CODEC, CraftingServer(), timeout_s=PLAY_TIMEOUT_S) as endpoint:
        context = GroupContext(endpoint, transcript, timeout_s=10.0)
        try:
            await GROUPS[group_id].run(context)
        finally:
            await context.close()
    return read(transcript, BOTS[group_id])


@functools.cache
def played(group_id: str) -> Play:
    """Play `group_id` against the fake once: every test of a Group reads that one play."""
    return asyncio.run(_play(group_id))


def clicks(window: Window) -> list[tuple[int, int, int]]:
    """The window's clicks: (slot, button, mode) each."""
    return [
        (int(str(f["slot"])), int(str(f["button"])), int(str(f["mode"])))
        for name, f in window.sent
        if name == CLICK
    ]


# Registration


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_each_group_is_exact_with_no_mask_on_the_default_spec(group_id: str) -> None:
    group = GROUPS[group_id]
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert group.kind is GroupKind.EXACT
    assert group.requires == ()
    assert group.masks == ()
    assert group.spec(default) == default


def test_the_windows_compare_the_slots_the_ghost_recipe_and_the_recipe_book() -> None:
    assert set(crafting.PACKETS) == {
        "minecraft:container_set_slot",
        "minecraft:container_set_content",
        "minecraft:set_cursor_item",
        "minecraft:place_ghost_recipe",
        "minecraft:recipe_book_add",
        "minecraft:recipe_book_remove",
        "minecraft:update_recipes",
    }
    assert len(crafting.PACKETS) == len(set(crafting.PACKETS))
    assert {window.label for window in played(GRID).windows} == {
        " ".join((OBSERVE_OPEN, *crafting.PACKETS))
    }


# What every Group sets up and undoes


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_the_joins_are_pinned_control_moves_away_and_the_bot_starts_empty(group_id: str) -> None:
    result = played(group_id)
    bot = BOTS[group_id]

    assert result.commands[:4] == (
        "gamerule player_movement_check false",
        "gamerule respawn_radius 0",
        "tp control 96.5 -60 96.5",
        f"clear {bot}",
    )


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_the_bot_is_emptied_and_put_back_at_the_spawn_and_the_joins_unpinned(
    group_id: str,
) -> None:
    after = played(group_id).after
    bot = BOTS[group_id]

    assert after[-4:] == (
        f"clear {bot}",
        f"tp {bot} 0.5 -60 0.5",
        "gamerule respawn_radius 10",
        "gamerule player_movement_check true",
    )


# crafting/grid


def test_each_grid_window_takes_the_stack_places_one_on_each_cell_and_puts_the_rest_back() -> None:
    result = played(GRID)

    assert len(result.windows) == len(crafting.GRID_CASES)
    for window, case in zip(result.windows, crafting.GRID_CASES, strict=True):
        placed = [(slot, 1, 0) for slot in case.slots]
        back = [(crafting.HOTBAR_0, 0, 0)] if case.count > len(case.slots) else []
        assert clicks(window) == [(crafting.HOTBAR_0, 0, 0), *placed, *back]
        assert window.before[-2:] == (
            f"clear {crafting.CRAFTER}",
            f"item replace entity {crafting.CRAFTER} hotbar.0 with {case.item} {case.count}",
        )


def test_a_grid_click_reports_the_one_item_it_put_in_the_cell() -> None:
    window = played(GRID).windows[0]  # one oak log, onto the top left cell
    sent = [f for name, f in window.sent if name == CLICK]

    assert sent[1]["changed_slots"] == [
        {
            "slot": 1,
            "item": {
                "item": _ITEMS.index("minecraft:oak_log"),
                "count": 1,
                "components": {"added": [], "removed": []},
            },
        }
    ]
    assert sent[1]["carried_item"] is None


def test_the_grid_cases_cover_shaped_shapeless_and_invalid_arrangements() -> None:
    items = {case.item for case in crafting.GRID_CASES}

    assert {"minecraft:oak_log", "minecraft:oak_planks", "minecraft:bone"} <= items
    assert crafting.Grid("minecraft:oak_planks", 2, (1, 4)) in crafting.GRID_CASES  # diagonal
    assert crafting.Grid("minecraft:oak_planks", 4, (1, 2, 3, 4)) in crafting.GRID_CASES
