"""The inventory Groups: what each Bot sends in each window, and what Control sets and undoes.

Every test reads one shared play of its Group against a fake server: the Transcript's
serverbound packets (Control's commands, the Bot's clicks and drops) and its Marks (the
Observation windows and the ticks stepped). What a server answers is never asserted: the fake
answers Control's markers and the barrier.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import cast, override

import pytest

from mscts.bot import SYNC_REQUESTS, Face
from mscts.codec.packets import Direction, Packet
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN, TICK_MARK
from mscts.group import GROUPS, GroupKind
from mscts.groups import inventory
from mscts.inventory import CLICK_MODES, OUTSIDE
from mscts.spec import ServerSpec
from mscts.transcript import Transcript
from tests.group import test_control
from tests.group.test_control import (
    CHAT_COMMAND,
    CLIENT_COMMAND,
    MARKER,
    ControlServer,
    playing,
    tree,
)
from tests.group.test_ticks import barriers_before_steps
from tests.net.fakes import Peer

GIVE, DROP = "inventory/give", "inventory/drop"
CLICKS_INVENTORY, CLICKS_CHEST = "inventory/clicks-inventory", "inventory/clicks-chest"
GROUP_IDS = (GIVE, DROP, CLICKS_INVENTORY, CLICKS_CHEST)
KINDS = {
    GIVE: GroupKind.EXACT,
    DROP: GroupKind.TICK_EXACT,
    CLICKS_INVENTORY: GroupKind.EXACT,
    CLICKS_CHEST: GroupKind.EXACT,
}
BOTS = {GIVE: "giver", DROP: "dropper", CLICKS_INVENTORY: "clicker", CLICKS_CHEST: "clicker"}
COMMANDS = tree(
    "gamerule",
    "tp",
    "tick",
    "gamemode",
    "give",
    "clear",
    "kill",
    "tag",
    "item",
    "setblock",
    "tellraw",
)
DROP_ITEM, DROP_ALL_ITEMS = 5, 4
"""The `player_action` actions of Q and Ctrl+Q (`ServerboundPlayerActionPacket$Action`)."""
CONTROL = "control"
SET_ENTITY_DATA = "minecraft:set_entity_data"
PLAYER_ACTION, CONTAINER_CLICK = "minecraft:player_action", "minecraft:container_click"
USE_ITEM_ON, CONTAINER_CLOSE = "minecraft:use_item_on", "minecraft:container_close"
ACTIONS = frozenset({PLAYER_ACTION, CONTAINER_CLICK, USE_ITEM_ON})
"""The Bot's packets a test reads in a window: what it does with its items."""
CHEST_BLOCK = (
    "minecraft:chest[facing=west]{Items:["
    '{Slot:0b,id:"minecraft:stone",count:10},'
    '{Slot:1b,id:"minecraft:dirt",count:64},'
    '{Slot:2b,id:"minecraft:diamond_sword",count:1},'
    '{Slot:3b,id:"minecraft:stone",count:5},'
    '{Slot:4b,id:"minecraft:oak_log",count:3}]}'
)
KIT = (
    "hotbar.0 with minecraft:stone 32",
    "hotbar.1 with minecraft:oak_log 16",
    "inventory.0 with minecraft:dirt 20",
    "inventory.2 with minecraft:diamond_helmet 1",
    "inventory.3 with minecraft:stone 64",
    "weapon.offhand with minecraft:torch 8",
)
GENERIC_9X3 = 2
"""`minecraft:generic_9x3`, a chest's menu, in `minecraft:menu` (registries report)."""
CHEST_TITLE = bytes([0x08, 0x00, 0x05]) + b"Chest"  # a network NBT String tag
GIVE_WINDOW = (
    "minecraft:container_set_content",
    "minecraft:container_set_slot",
    "minecraft:set_cursor_item",
    "minecraft:set_player_inventory",
    "minecraft:add_entity",
    SET_ENTITY_DATA,
    "minecraft:take_item_entity",
    "minecraft:remove_entities",
    "minecraft:sound",
)
"""What a give window compares, as its Mark names it."""
DROP_WINDOW = (
    "minecraft:container_set_slot",
    "minecraft:set_player_inventory",
    "minecraft:add_entity",
    SET_ENTITY_DATA,
    "minecraft:take_item_entity",
    "minecraft:remove_entities",
    "minecraft:sound",
)
"""What a drop window compares: the slot, the item thrown, and the item picked up."""
CLICK_WINDOW = (
    "minecraft:open_screen",
    "minecraft:container_set_content",
    "minecraft:container_set_slot",
    "minecraft:set_cursor_item",
    "minecraft:set_player_inventory",
    "minecraft:add_entity",
    SET_ENTITY_DATA,
    "minecraft:sound",
)
"""What a click window compares: the menus, an item thrown out, and a sound."""


def label(packets: tuple[str, ...]) -> str:
    """The open Mark of a window that compares `packets`."""
    return f"{OBSERVE_OPEN} {' '.join(packets)}"


UNDONE_FIRST = {CLICKS_CHEST: ("setblock 2 -60 0 minecraft:air",)}
"""What a Group undoes before the undo every Group shares."""

ITEMS = "@e[type=minecraft:item,x=0.5,y=-60,z=0.5,distance=..20"
TAG = "mscts_inventory_before"
KILL_NEW_ITEMS = f"kill {ITEMS},tag=!{TAG}]"


@dataclass(frozen=True)
class Window:
    """One Observation window: Control's commands before it and in it, the Bot's actions, ticks."""

    label: str
    before: tuple[str, ...]
    commands: tuple[str, ...]
    sent: tuple[tuple[str, dict[str, object]], ...]
    ticks: int


@dataclass(frozen=True)
class Play:
    """A played Group: its windows, and Control's commands before the first and after the last."""

    windows: tuple[Window, ...]
    first: tuple[str, ...]
    after: tuple[str, ...]
    timeline: tuple[str, ...]
    """Control's commands, the Bot's closes (`close <window id>`) and its syncs, in order."""
    barriers: tuple[int, ...]
    """For each drop a step follows: the Bot's barrier requests in between."""


def _commands(transcript: Transcript) -> list[tuple[int, str]]:
    """Control's commands with when, but its markers."""
    commands = [
        (event.t_ns, str((event.packet.fields or {})["command"]))
        for event in transcript.events
        if event.bot == CONTROL
        and event.packet.direction is Direction.SERVERBOUND
        and event.packet.name == CHAT_COMMAND
    ]
    return [(t_ns, command) for t_ns, command in commands if not command.startswith(MARKER)]


def read(transcript: Transcript, bot: str) -> Play:
    """The windows of `transcript`, each from its open Mark to its last close Mark."""
    labels = [mark.label for mark in transcript.marks if mark.label.startswith(OBSERVE_OPEN)]
    opens = [mark.t_ns for mark in transcript.marks if mark.label.startswith(OBSERVE_OPEN)]
    closes = [mark.t_ns for mark in transcript.marks if mark.label == OBSERVE_CLOSE]
    assert len(opens) == len(closes), transcript.marks
    ticks = [
        m.t_ns for m in transcript.marks if m.label.startswith(TICK_MARK) and " " not in m.label
    ]
    actions = [
        (event.t_ns, event.packet.name, dict(event.packet.fields or {}))
        for event in transcript.events
        if event.bot == bot
        and event.packet.direction is Direction.SERVERBOUND
        and event.packet.name in ACTIONS
    ]
    control = _commands(transcript)
    windows, previous = [], 0
    for label, opened, closed in zip(labels, opens, closes, strict=True):
        windows.append(
            Window(
                label=label,
                before=tuple(c for t, c in control if previous <= t < opened),
                commands=tuple(c for t, c in control if opened <= t <= closed),
                sent=tuple((name, f) for t, name, f in actions if opened <= t <= closed),
                ticks=sum(opened <= t <= closed for t in ticks),
            )
        )
        previous = closed
    first = tuple(c for t, c in control if t < opens[0]) if opens else ()
    after = tuple(c for t, c in control if t > previous)
    return Play(
        tuple(windows),
        first,
        after,
        _timeline(transcript, bot, control),
        tuple(barriers_before_steps(transcript, bot, {PLAYER_ACTION})),
    )


def _timeline(transcript: Transcript, bot: str, control: list[tuple[int, str]]) -> tuple[str, ...]:
    """Control's commands among the Bot's closes and syncs, by when each was sent."""
    own = [
        (event.t_ns, _said(event.packet))
        for event in transcript.events
        if event.bot == bot
        and event.packet.direction is Direction.SERVERBOUND
        and event.packet.name in {CONTAINER_CLOSE, CLIENT_COMMAND}
    ]
    return tuple(entry for _, entry in sorted([*own, *control]))


def _said(packet: Packet) -> str:
    """`close <window id>` for a container_close, `sync` for a statistics request."""
    if packet.name == CONTAINER_CLOSE:
        return f"close {(packet.fields or {})['window_id']}"
    return "sync"


@dataclass
class ChestServer(ControlServer):
    """A ControlServer that opens a 3-row chest for each `use_item_on`, as vanilla does.

    Each open gets the next window id, from 1 (`ServerPlayer.nextContainerCounter`).
    """

    _windows: int = field(default=0, init=False)

    @override
    async def _play(self, peer: Peer) -> None:
        await super()._play(cast("Peer", _Opening(peer, self)))

    async def opened(self, peer: Peer) -> None:
        """Send the next chest's `open_screen`."""
        self._windows += 1
        frame = peer.frame(
            "minecraft:open_screen",
            window_id=self._windows,
            window_type=GENERIC_9X3,
            window_title=CHEST_TITLE,
        )
        await peer.write(frame)


class _Opening:
    """`peer`, but each `use_item_on` it reads opens a chest first."""

    def __init__(self, peer: Peer, server: ChestServer) -> None:
        self._peer = peer
        self._server = server

    def __getattr__(self, name: str) -> object:
        return getattr(self._peer, name)

    async def packets(self) -> AsyncIterator[Packet]:
        async for packet in self._peer.packets():
            if packet.name == USE_ITEM_ON:
                await self._server.opened(self._peer)
            yield packet


async def replay(group_id: str, server: ControlServer) -> Play:
    """Play `group_id` against `server`; return what was read from its Transcript."""
    transcript = Transcript(group_id=group_id, server="fake")
    async with playing(server, transcript) as context:
        await GROUPS[group_id].run(context)
    return read(transcript, BOTS[group_id])


_PLAYS: dict[str, Play] = {}
"""Each Group's play against a default `ChestServer`; no test changes it."""


async def played(group_id: str) -> Play:
    """The play of `group_id` against a default fake server, played the first time it is asked."""
    if group_id not in _PLAYS:
        _PLAYS[group_id] = await replay(group_id, ChestServer(commands=COMMANDS))
    return _PLAYS[group_id]


@pytest.fixture(autouse=True)
def long_play(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(test_control, "PLAY_TIMEOUT_S", 280.0)


pytestmark = pytest.mark.timeout(300)


# Every Group


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_each_group_is_registered_with_its_kind_and_the_default_spec(group_id: str) -> None:
    group = GROUPS[group_id]
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert group.kind is KINDS[group_id]
    assert group.requires == ()
    assert group.spec(default) == default


@pytest.mark.parametrize("group_id", GROUP_IDS)
@pytest.mark.asyncio
async def test_control_pins_the_joins_moves_away_and_tags_what_lies_there_first(
    group_id: str,
) -> None:
    first = (await played(group_id)).first

    assert first[:4] == (
        "gamerule player_movement_check false",
        "gamerule respawn_radius 0",
        "tp control 96.5 -60 96.5",
        f"tag {ITEMS}] add {TAG}",
    )
    bot = BOTS[group_id]
    assert first.index(f"gamemode survival {bot}") < first.index("tick freeze")
    assert f"clear {bot}" in first
    assert f"tp {bot} 0.5 -60 0.5 0 90" in first


@pytest.mark.parametrize("group_id", GROUP_IDS)
@pytest.mark.asyncio
async def test_control_kills_the_new_items_then_clears_the_bot_and_undoes_the_rest(
    group_id: str,
) -> None:
    own = UNDONE_FIRST.get(group_id, ())
    after = (await played(group_id)).after
    bot = BOTS[group_id]

    assert after[: len(own)] == own
    after = after[len(own) :]
    assert after[:3] == (KILL_NEW_ITEMS, f"clear {bot}", f"tp {bot} 0.5 -60 0.5")
    assert after[3:] == (
        f"tag {ITEMS}] remove {TAG}",
        "gamerule respawn_radius 10",
        "gamerule player_movement_check true",
        "tick unfreeze",
    )


# `inventory/give`


def test_give_masks_the_dropped_items_motion_and_the_pickup_sounds_pitch() -> None:
    masks = {(mask.packet, mask.path) for mask in GROUPS[GIVE].masks}

    assert masks == {
        ("minecraft:add_entity", "velocity.x"),
        ("minecraft:add_entity", "velocity.y"),
        ("minecraft:add_entity", "velocity.z"),
        ("minecraft:add_entity", "yaw"),
        ("minecraft:sound", "pitch"),
    }


@pytest.mark.asyncio
async def test_give_runs_one_give_in_each_window_then_steps_a_tick() -> None:
    windows = (await played(GIVE)).windows

    assert [window.commands for window in windows] == [
        ("give giver minecraft:stone 1", "tick step 1"),
        ("give giver minecraft:stone 64", "tick step 1"),
        ("give giver minecraft:stone 100", "tick step 1"),
        ("give giver minecraft:diamond_sword 1", "tick step 1"),
        ("give giver minecraft:stone 1", "tick step 1"),
    ]


@pytest.mark.asyncio
async def test_only_the_give_that_makes_two_items_leaves_out_their_entity_data() -> None:
    # Vanilla resends each new entity's data at the end of the tick in the hash order of its id.
    labels = [window.label for window in (await played(GIVE)).windows]
    compared = label(GIVE_WINDOW)
    no_data = label(tuple(name for name in GIVE_WINDOW if name != SET_ENTITY_DATA))

    assert labels == [compared, compared, no_data, compared, compared]


@pytest.mark.asyncio
async def test_each_give_steps_a_tick_in_which_vanilla_removes_the_item_it_showed() -> None:
    # GiveCommand.giveItem makes a fake item (ItemEntity.makeFakeItem: age 5999), which
    # ItemEntity.tick discards on the next tick; the frozen world steps that tick in the window.
    assert [window.ticks for window in (await played(GIVE)).windows] == [1, 1, 1, 1, 1]


@pytest.mark.asyncio
async def test_each_give_starts_from_an_empty_inventory_with_no_new_item_left() -> None:
    windows = (await played(GIVE)).windows

    for window in windows[:-1]:
        assert window.before[-2:] == (KILL_NEW_ITEMS, "clear giver")
    assert [len(window.before) for window in windows[1:]] == [2, 2, 2, 3]


@pytest.mark.asyncio
async def test_the_last_give_finds_the_inventory_full() -> None:
    before = (await played(GIVE)).windows[-1].before

    assert before == (KILL_NEW_ITEMS, "clear giver", "give giver minecraft:dirt 2304")


# `inventory/drop`


def test_drop_masks_only_the_dropped_items_motion() -> None:
    masks = {(mask.packet, mask.path) for mask in GROUPS[DROP].masks}

    assert masks == {
        ("minecraft:add_entity", "velocity.x"),
        ("minecraft:add_entity", "velocity.y"),
        ("minecraft:add_entity", "velocity.z"),
        ("minecraft:add_entity", "yaw"),
    }


@pytest.mark.asyncio
async def test_every_drop_window_compares_the_slot_the_thrown_item_and_its_pickup() -> None:
    labels = [window.label for window in (await played(DROP)).windows]

    assert labels == [label(DROP_WINDOW)] * 4


def actions(window: Window) -> list[int]:
    return [int(str(fields["action"])) for name, fields in window.sent if name == PLAYER_ACTION]


@pytest.mark.asyncio
async def test_the_bot_presses_q_once_in_each_window_and_ctrl_q_in_the_second() -> None:
    windows = (await played(DROP)).windows

    assert [actions(window) for window in windows] == [
        [DROP_ITEM],
        [DROP_ALL_ITEMS],
        [DROP_ITEM],
        [DROP_ITEM],
    ]


@pytest.mark.asyncio
async def test_each_drop_reaches_the_server_before_the_steps_after_it() -> None:
    result = await played(DROP)

    assert len(result.barriers) == len(result.windows)
    assert set(result.barriers) == {SYNC_REQUESTS}


@pytest.mark.asyncio
async def test_only_the_first_drop_steps_past_the_pickup_delay() -> None:
    # The pickup delay is 40 item ticks (LivingEntity.createItemStackToDrop); the player picks
    # the item up on the 40th, and the 41st shows that nothing comes after.
    assert [window.ticks for window in (await played(DROP)).windows] == [41, 1, 1, 1]


@pytest.mark.asyncio
async def test_each_drop_starts_from_its_item_alone_in_the_first_hotbar_slot() -> None:
    held = [window.before[-3:] for window in (await played(DROP)).windows]

    assert held == [
        (KILL_NEW_ITEMS, "clear dropper", f"item replace entity dropper hotbar.0 with {item}")
        for item in (
            "minecraft:stone 64",
            "minecraft:stone 64",
            "minecraft:diamond_sword 1",
            "minecraft:air",
        )
    ]


# `inventory/clicks-inventory` and `inventory/clicks-chest`


def test_the_inventory_clicks_are_registered_before_the_chests_so_they_are_played_first() -> None:
    # A Candidate that cannot open a chest fails the chest Group at its first click.
    ids = list(GROUPS)

    assert ids.index(CLICKS_INVENTORY) < ids.index(CLICKS_CHEST)


def test_the_inventory_clicks_mask_only_the_thrown_items_motion() -> None:
    # The helmet's equip sound has a fixed pitch (LivingEntity.onEquipItem plays it at 1.0).
    masks = {(mask.packet, mask.path) for mask in GROUPS[CLICKS_INVENTORY].masks}

    assert masks == {
        ("minecraft:add_entity", "velocity.x"),
        ("minecraft:add_entity", "velocity.y"),
        ("minecraft:add_entity", "velocity.z"),
        ("minecraft:add_entity", "yaw"),
    }


def test_the_chest_clicks_mask_the_thrown_items_motion_and_the_chests_sound_pitch() -> None:
    masks = {(mask.packet, mask.path) for mask in GROUPS[CLICKS_CHEST].masks}

    assert masks == {
        ("minecraft:add_entity", "velocity.x"),
        ("minecraft:add_entity", "velocity.y"),
        ("minecraft:add_entity", "velocity.z"),
        ("minecraft:add_entity", "yaw"),
        ("minecraft:sound", "pitch"),
    }


KIT_COMMANDS = (
    "clear clicker",
    *(f"item replace entity clicker {entry}" for entry in KIT),
)
"""How Control gives the Bot its kit: an empty inventory, then each item."""


@pytest.mark.asyncio
async def test_control_gives_the_kit_before_the_first_inventory_click() -> None:
    before = (await played(CLICKS_INVENTORY)).windows[0].before

    assert before[-7:] == KIT_COMMANDS
    assert not any(command.startswith("setblock") for command in before)


@pytest.mark.asyncio
async def test_control_places_the_filled_chest_and_gives_the_kit_before_the_chest_opens() -> None:
    before = (await played(CLICKS_CHEST)).windows[0].before

    assert before[-9:] == (
        "setblock 2 -60 0 minecraft:air",
        f"setblock 2 -60 0 {CHEST_BLOCK}",
        *KIT_COMMANDS,
    )


@pytest.mark.parametrize(("group_id", "windows"), [(CLICKS_INVENTORY, 15), (CLICKS_CHEST, 15)])
@pytest.mark.asyncio
async def test_every_click_window_compares_the_menus_a_thrown_item_and_the_sound(
    group_id: str, windows: int
) -> None:
    labels = [window.label for window in (await played(group_id)).windows]

    assert labels == [label(CLICK_WINDOW)] * windows


@pytest.mark.asyncio
async def test_the_chest_clicks_say_so_when_the_chest_does_not_open() -> None:
    # A server that opens nothing: the Bot's first click would land on its own inventory menu.
    with pytest.raises(ValueError, match="the chest did not open"):
        await replay(CLICKS_CHEST, ControlServer(commands=COMMANDS))


def opens(window: Window) -> list[tuple[object, object]]:
    """Where and on which face the Bot uses its hand in `window`."""
    return [(f["pos"], f["face"]) for name, f in window.sent if name == USE_ITEM_ON]


@pytest.mark.asyncio
async def test_the_bot_opens_the_chest_in_the_first_window_and_again_in_the_last() -> None:
    windows = (await played(CLICKS_CHEST)).windows
    chest = ({"x": 2, "y": -60, "z": 0}, int(Face.UP))

    assert [i for i, window in enumerate(windows) if opens(window)] == [0, 14]
    assert [opens(windows[i]) for i in (0, 14)] == [[chest]] * 2
    assert len(windows) == 15


@pytest.mark.asyncio
async def test_the_inventory_clicks_open_nothing() -> None:
    windows = (await played(CLICKS_INVENTORY)).windows

    assert [opens(window) for window in windows] == [[]] * 15


def clicks(window: Window) -> list[tuple[int, int, int, int]]:
    """The window id, slot, button and mode of each click the Bot sends in `window`."""
    return [
        (int(str(f["window_id"])), int(str(f["slot"])), int(str(f["button"])), int(str(f["mode"])))
        for name, f in window.sent
        if name == CONTAINER_CLICK
    ]


PICKUP, QUICK_MOVE, SWAP, THROW, QUICK_CRAFT, PICKUP_ALL = 0, 1, 2, 4, 5, 6
"""`ClickType` ordinals (26.3 javap), as `container_click` sends the mode."""


@pytest.mark.asyncio
async def test_the_first_chest_windows_take_and_split_a_stack_and_shift_click_both_ways() -> None:
    windows = (await played(CLICKS_CHEST)).windows

    assert [clicks(window) for window in windows[1:5]] == [
        [(1, 0, 0, PICKUP), (1, 5, 0, PICKUP)],
        [(1, 1, 1, PICKUP), (1, 6, 1, PICKUP), (1, 6, 0, PICKUP)],
        [(1, 2, 0, QUICK_MOVE)],
        [(1, 54, 0, QUICK_MOVE)],
    ]


@pytest.mark.asyncio
async def test_the_first_inventory_windows_shift_click_the_helmet_onto_the_head_and_back() -> None:
    windows = (await played(CLICKS_INVENTORY)).windows

    assert [clicks(window) for window in windows[4:6]] == [
        [(0, 11, 0, QUICK_MOVE)],
        [(0, 5, 0, QUICK_MOVE)],
    ]


def modes(sequence: tuple[tuple[int, int, str], ...]) -> list[tuple[int, int, int]]:
    return [(slot, button, CLICK_MODES[mode]) for slot, button, mode in sequence]


@pytest.mark.asyncio
async def test_each_group_clicks_its_sequences_in_its_own_menu() -> None:
    chest = [[(1, *click) for click in modes(s)] for s in inventory.CHEST_CLICKS]
    own = [[(0, *click) for click in modes(s)] for s in inventory.INVENTORY_CLICKS]

    assert [clicks(window) for window in (await played(CLICKS_CHEST)).windows[1:14]] == chest
    assert [clicks(window) for window in (await played(CLICKS_INVENTORY)).windows] == own


CLICKED = {
    (PICKUP, 0),
    (PICKUP, 1),
    (QUICK_MOVE, 0),
    *((SWAP, key) for key in (*range(9), 40)),
    (QUICK_CRAFT, 0),
    (QUICK_CRAFT, 1),
    (QUICK_CRAFT, 2),
    (QUICK_CRAFT, 4),
    (QUICK_CRAFT, 5),
    (QUICK_CRAFT, 6),
    (PICKUP_ALL, 0),
    (THROW, 0),
    (THROW, 1),
}
"""Every mode and button the issue names: left and right, shift, the keys 1-9 and F, both
drags (start, add, end), double-click, Q and Ctrl+Q."""


@pytest.mark.parametrize("group_id", [CLICKS_INVENTORY, CLICKS_CHEST])
@pytest.mark.asyncio
async def test_each_group_clicks_every_mode_and_button_and_outside_the_window(
    group_id: str,
) -> None:
    windows = (await played(group_id)).windows
    sent = [click for window in windows for click in clicks(window)]

    assert {(mode, button) for _, _, button, mode in sent} == CLICKED
    assert (OUTSIDE, 0, PICKUP) in {(slot, button, mode) for _, slot, button, mode in sent}
    assert (OUTSIDE, 1, PICKUP) in {(slot, button, mode) for _, slot, button, mode in sent}


@pytest.mark.parametrize(
    ("group_id", "closed"),
    [(CLICKS_INVENTORY, ["close 0"]), (CLICKS_CHEST, ["close 1", "close 2"])],
)
@pytest.mark.asyncio
async def test_the_bot_closes_each_menu_and_syncs_before_control_acts_again(
    group_id: str, closed: list[str]
) -> None:
    timeline = (await played(group_id)).timeline
    closes = [i for i, entry in enumerate(timeline) if entry.startswith("close")]

    assert [timeline[i] for i in closes] == closed
    assert all(timeline[i + 1] == "sync" for i in closes)
