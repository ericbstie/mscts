"""The dropped item Groups: what Control summons and steps in each window, and what it undoes.

Every test reads one shared play of its Group against a fake server: Control's commands and the
Marks (the Observation windows and the ticks stepped). What a server answers is never asserted:
the fake answers Control's markers and the barrier.
"""

from dataclasses import dataclass

import pytest

from mscts.codec.packets import Direction
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN, TICK_MARK
from mscts.group import GROUPS, GroupKind
from mscts.spec import ServerSpec
from mscts.transcript import Transcript
from tests.group import test_control
from tests.group.test_control import CHAT_COMMAND, MARKER, ControlServer, playing, tree

MERGE = "entities/item-merge"
GROUP_IDS = (MERGE,)
BOTS = {MERGE: "watcher"}
COMMANDS = tree(
    "gamerule",
    "tp",
    "tick",
    "gamemode",
    "clear",
    "xp",
    "kill",
    "summon",
    "item",
    "setblock",
    "tellraw",
)
CONTROL = "control"
TAG = "mscts_items"
STILL = 'Motion:[0.0d,0.0d,0.0d],NoGravity:1b,Tags:["mscts_items"]'
WINDOW = (
    f"{OBSERVE_OPEN} minecraft:add_entity minecraft:set_entity_data minecraft:remove_entities "
    "minecraft:take_item_entity minecraft:container_set_slot minecraft:set_player_inventory "
    "minecraft:set_experience minecraft:sound"
)
"""The open Mark of every window."""


def item(place: str, stack: str, *more: str) -> str:
    """The summon of a still, tagged item of `stack` (`<id> <count>`) at `place`."""
    item_id, count = stack.split()
    fields = ",".join((f'Item:{{id:"{item_id}",count:{count}}}', STILL, *more))
    return f"summon minecraft:item {place} {{{fields}}}"


@dataclass(frozen=True)
class Window:
    """One Observation window: its open Mark, Control's commands before it and in it, its ticks."""

    label: str
    before: tuple[str, ...]
    commands: tuple[str, ...]
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


def read(transcript: Transcript) -> Play:
    """The windows of `transcript`, each from its open Mark to its last close Mark."""
    labels = [mark.label for mark in transcript.marks if mark.label.startswith(OBSERVE_OPEN)]
    opens = [mark.t_ns for mark in transcript.marks if mark.label.startswith(OBSERVE_OPEN)]
    closes = [mark.t_ns for mark in transcript.marks if mark.label == OBSERVE_CLOSE]
    assert len(opens) == len(closes), transcript.marks
    ticks = [
        m.t_ns for m in transcript.marks if m.label.startswith(TICK_MARK) and " " not in m.label
    ]
    control = _commands(transcript)
    windows, previous = [], 0
    for label, opened, closed in zip(labels, opens, closes, strict=True):
        windows.append(
            Window(
                label=label,
                before=tuple(c for t, c in control if previous <= t < opened),
                commands=tuple(c for t, c in control if opened <= t <= closed),
                ticks=sum(opened <= t <= closed for t in ticks),
            )
        )
        previous = closed
    first = tuple(c for t, c in control if t < opens[0]) if opens else ()
    after = tuple(c for t, c in control if t > previous)
    return Play(tuple(windows), first, after)


async def replay(group_id: str, server: ControlServer) -> Play:
    """Play `group_id` against `server`; return what was read from its Transcript."""
    transcript = Transcript(group_id=group_id, server="fake")
    async with playing(server, transcript) as context:
        await GROUPS[group_id].run(context)
    return read(transcript)


_PLAYS: dict[str, Play] = {}
"""Each Group's play against a default fake server; no test changes it."""


async def play(group_id: str) -> Play:
    """The play of `group_id` against a default fake server, played the first time it is asked."""
    if group_id not in _PLAYS:
        _PLAYS[group_id] = await replay(group_id, ControlServer(commands=COMMANDS))
    return _PLAYS[group_id]


@pytest.fixture(autouse=True)
def long_play(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(test_control, "PLAY_TIMEOUT_S", 280.0)


pytestmark = pytest.mark.timeout(300)


# Every Group


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_each_group_is_registered_tick_exact_with_the_default_spec(group_id: str) -> None:
    group = GROUPS[group_id]
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert group.kind is GroupKind.TICK_EXACT
    assert group.requires == ()
    assert group.spec(default) == default


@pytest.mark.parametrize("group_id", GROUP_IDS)
@pytest.mark.asyncio
async def test_control_pins_the_joins_moves_away_and_empties_the_bot_before_the_freeze(
    group_id: str,
) -> None:
    bot = BOTS[group_id]

    first = (await play(group_id)).first

    assert first[:8] == (
        "gamerule player_movement_check false",
        "gamerule respawn_radius 0",
        "tp control 96.5 -60 96.5",
        f"gamemode survival {bot}",
        f"clear {bot}",
        f"xp set {bot} 0 levels",
        f"xp set {bot} 0 points",
        "tick freeze",
    )


@pytest.mark.parametrize("group_id", GROUP_IDS)
@pytest.mark.asyncio
async def test_control_kills_what_it_summoned_then_empties_the_bot_and_undoes_the_rest(
    group_id: str,
) -> None:
    # The summoned items go first: a player picks up an item as soon as it has room.
    bot = BOTS[group_id]

    after = (await play(group_id)).after

    assert after[-8:] == (
        f"kill @e[tag={TAG}]",
        f"clear {bot}",
        f"xp set {bot} 0 levels",
        f"xp set {bot} 0 points",
        f"tp {bot} 0.5 -60 0.5",
        "gamerule respawn_radius 10",
        "gamerule player_movement_check true",
        "tick unfreeze",
    )


# `entities/item-merge`

STONE_2, STONE_3 = "minecraft:stone 2", "minecraft:stone 3"
PAIRS = (
    item("-10.85 -60.0 6.5", STONE_2),
    item("-10.15 -60.0 6.5", STONE_3),
    "tick step 1",
    item("-7.85 -60.0 6.5", STONE_2),
    item("-7.05 -60.0 6.5", STONE_3),
    "tick step 1",
    item("-4.85 -60.0 6.5", STONE_2),
    item("-4.85 -59.8 6.5", STONE_3),
    "tick step 1",
    item("-1.85 -60.0 6.5", STONE_2),
    item("-1.85 -59.7 6.5", STONE_3),
    "tick step 1",
    "setblock 1 -60 6 minecraft:glass_pane",
    item("1.15 -60.0 6.5", STONE_2),
    item("1.85 -60.0 6.5", STONE_3),
    "tick step 1",
    item("4.15 -60.0 6.5", STONE_2),
    item("4.45 -60.0 6.5", "minecraft:dirt 3"),
    "tick step 1",
    item("7.15 -60.0 6.5", "minecraft:stone 40"),
    item("7.45 -60.0 6.5", "minecraft:stone 30"),
    "tick step 1",
    item("10.15 -60.0 6.5", "minecraft:stone 32"),
    item("10.45 -60.0 6.5", "minecraft:stone 32"),
)
"""The pairs, a tick apart, so that each merges on a tick of its own: two items 0.7 apart and 0.8
apart, 0.2 above and 0.3 above, 0.7 apart with a pane between, two different items, two stacks
that make more than 64, and two that make 64."""


@pytest.mark.asyncio
async def test_merge_summons_each_pair_a_tick_after_the_one_before_it() -> None:
    first = (await play(MERGE)).first

    assert first[8:] == PAIRS


@pytest.mark.asyncio
async def test_merge_steps_one_window_until_the_last_pair_has_merged_and_a_tick_more() -> None:
    # An item looks for another to merge with on every 40th of its own ticks
    # (ItemEntity.tick); the last pair was summoned 7 ticks after the first.
    (window,) = (await play(MERGE)).windows

    assert window.label == WINDOW
    assert window.commands == ("tick step 1",) * 41
    assert window.ticks == 41


@pytest.mark.asyncio
async def test_merge_takes_the_pane_away_first() -> None:
    after = (await play(MERGE)).after

    assert after[:-8] == ("setblock 1 -60 6 minecraft:air",)
