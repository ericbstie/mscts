"""The inventory Groups: what each Bot sends in each window, and what Control sets and undoes.

Every test reads one shared play of its Group against a fake server: the Transcript's
serverbound packets (Control's commands, the Bot's clicks and drops) and its Marks (the
Observation windows and the ticks stepped). What a server answers is never asserted: the fake
answers Control's markers and the barrier.
"""

import asyncio
import functools
from dataclasses import dataclass

import pytest

from mscts.codec.packets import Direction
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN, TICK_MARK
from mscts.group import GROUPS, GroupKind
from mscts.groups import inventory
from mscts.spec import ServerSpec
from mscts.transcript import Transcript
from tests.group import test_control
from tests.group.test_control import CHAT_COMMAND, MARKER, ControlServer, playing, tree

GIVE = "inventory/give"
GROUP_IDS = (GIVE,)
KINDS = {GIVE: GroupKind.EXACT}
BOTS = {GIVE: "giver"}
COMMANDS = tree("gamerule", "tp", "tick", "gamemode", "give", "clear", "kill", "tag", "tellraw")
CONTROL = "control"
SET_ENTITY_DATA = "minecraft:set_entity_data"
ACTIONS = frozenset({"minecraft:player_action", "minecraft:container_click"})
"""The Bot's packets a test reads: what it does with its items."""

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
    return Play(tuple(windows), first, tuple(c for t, c in control if t > previous))


async def _play(group_id: str) -> Play:
    transcript = Transcript(group_id=group_id, server="fake")
    async with playing(ControlServer(commands=COMMANDS), transcript) as context:
        await GROUPS[group_id].run(context)
    return read(transcript, BOTS[group_id])


@functools.cache
def played(group_id: str) -> Play:
    """Play `group_id` against a fake server once: every test of a Group reads that play."""
    return asyncio.run(_play(group_id))


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
def test_control_pins_the_joins_moves_away_and_tags_what_lies_there_first(group_id: str) -> None:
    first = played(group_id).first

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
def test_control_kills_the_new_items_then_clears_the_bot_and_undoes_the_rest(
    group_id: str,
) -> None:
    after = played(group_id).after
    bot = BOTS[group_id]

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


def test_give_runs_one_give_in_each_window() -> None:
    windows = played(GIVE).windows

    assert [window.commands for window in windows] == [
        ("give giver minecraft:stone 1",),
        ("give giver minecraft:stone 64",),
        ("give giver minecraft:stone 100",),
        ("give giver minecraft:diamond_sword 1",),
        ("give giver minecraft:stone 1",),
    ]


def test_only_the_give_that_makes_two_items_leaves_out_their_entity_data() -> None:
    # Vanilla resends each new entity's data at the end of the tick in the hash order of its id.
    labels = [window.label for window in played(GIVE).windows]
    compared = f"{OBSERVE_OPEN} {' '.join(inventory.GIVE_PACKETS)}"
    no_data = tuple(name for name in inventory.GIVE_PACKETS if name != SET_ENTITY_DATA)

    assert labels == [compared, compared, f"{OBSERVE_OPEN} {' '.join(no_data)}", compared, compared]
    assert SET_ENTITY_DATA in inventory.GIVE_PACKETS


def test_each_give_starts_from_an_empty_inventory_with_no_new_item_left() -> None:
    windows = played(GIVE).windows

    for window in windows[:-1]:
        assert window.before[-2:] == (KILL_NEW_ITEMS, "clear giver")
    assert [len(window.before) for window in windows[1:]] == [2, 2, 2, 3]


def test_the_last_give_finds_the_inventory_full() -> None:
    before = played(GIVE).windows[-1].before

    assert before == (KILL_NEW_ITEMS, "clear giver", "give giver minecraft:dirt 2304")
