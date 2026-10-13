"""The block physics Groups: what Control builds, removes and steps in each window, and undoes.

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

GRAVITY, SUPPORT = "blocks/gravity", "blocks/support"
GROUP_IDS = (GRAVITY, SUPPORT)
COMMANDS = tree("gamerule", "tp", "tick", "setblock", "fill", "kill", "tellraw")
CONTROL = "control"
KILL_ITEMS = "kill @e[type=minecraft:item]"
STEP = "tick step 1"


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
    opens = [mark for mark in transcript.marks if mark.label.startswith(OBSERVE_OPEN)]
    closes = [mark.t_ns for mark in transcript.marks if mark.label == OBSERVE_CLOSE]
    assert len(opens) == len(closes), transcript.marks
    ticks = [
        m.t_ns for m in transcript.marks if m.label.startswith(TICK_MARK) and " " not in m.label
    ]
    control = _commands(transcript)
    windows, previous = [], 0
    for opened, closed in zip(opens, closes, strict=True):
        windows.append(
            Window(
                label=opened.label,
                before=tuple(c for t, c in control if previous <= t < opened.t_ns),
                commands=tuple(c for t, c in control if opened.t_ns <= t <= closed),
                ticks=sum(opened.t_ns <= t <= closed for t in ticks),
            )
        )
        previous = closed
    first = tuple(c for t, c in control if t < opens[0].t_ns)
    after = tuple(c for t, c in control if t > previous)
    return Play(tuple(windows), first, after)


_PLAYS: dict[str, Play] = {}
"""Each Group's play against a default fake server; no test changes it."""


async def play(group_id: str) -> Play:
    """The play of `group_id` against a default fake server, played the first time it is asked."""
    if group_id not in _PLAYS:
        transcript = Transcript(group_id=group_id, server="fake")
        async with playing(ControlServer(commands=COMMANDS), transcript) as context:
            await GROUPS[group_id].run(context)
        _PLAYS[group_id] = read(transcript)
    return _PLAYS[group_id]


@pytest.fixture(autouse=True)
def long_play(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(test_control, "PLAY_TIMEOUT_S", 280.0)


pytestmark = pytest.mark.timeout(300)


# Both Groups

SETUP = (
    "gamerule player_movement_check false",
    "gamerule respawn_radius 0",
    "tp control 96.5 -60 96.5",
    "gamerule random_tick_speed 0",
    "tick freeze",
)
"""What Control does before it builds: pins the joins, moves away, stops random ticks, freezes."""


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_each_group_is_registered_tick_exact_with_the_default_spec(group_id: str) -> None:
    group = GROUPS[group_id]
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert group.kind is GroupKind.TICK_EXACT
    assert group.requires == ()
    assert group.spec(default) == default


@pytest.mark.parametrize("group_id", GROUP_IDS)
@pytest.mark.asyncio
async def test_control_pins_the_joins_moves_away_and_freezes_before_it_builds(
    group_id: str,
) -> None:
    first = (await play(group_id)).first

    assert first[: len(SETUP)] == SETUP


@pytest.mark.parametrize("group_id", GROUP_IDS)
@pytest.mark.asyncio
async def test_control_steps_five_ticks_after_building_so_what_the_layouts_scheduled_has_run(
    group_id: str,
) -> None:
    # A falling block schedules a tick 2 ticks after it is placed, water 5
    # (FallingBlock.onPlace): run them before the first window, while nothing is loose.
    first = (await play(group_id)).first

    assert first[-5:] == (STEP,) * 5


@pytest.mark.parametrize("group_id", GROUP_IDS)
@pytest.mark.asyncio
async def test_each_window_removes_one_block_then_steps_its_ticks(group_id: str) -> None:
    windows = (await play(group_id)).windows

    for window, (release, ticks) in zip(windows, RELEASES[group_id], strict=True):
        assert window.commands == (f"setblock {release} minecraft:air", *(STEP,) * ticks)
        assert window.ticks == ticks


@pytest.mark.parametrize("group_id", GROUP_IDS)
@pytest.mark.asyncio
async def test_control_clears_the_blocks_kills_the_items_then_sets_everything_back(
    group_id: str,
) -> None:
    after = (await play(group_id)).after

    assert after[-7:] == (
        CLEARS[group_id],
        KILL_ITEMS,
        "gamerule random_tick_speed 3",
        "tp watcher 0.5 -60 0.5",
        "gamerule respawn_radius 10",
        "gamerule player_movement_check true",
        "tick unfreeze",
    )


# `blocks/gravity`

COLUMN = (
    "setblock 2 -60 8 minecraft:stone",
    "setblock 2 -59 8 minecraft:sand",
    "setblock 2 -58 8 minecraft:gravel",
    "setblock 2 -57 8 minecraft:red_sand",
    "setblock 2 -56 8 minecraft:sand",
    "setblock 2 -55 8 minecraft:gravel",
    "setblock 2 -54 8 minecraft:red_sand",
)
POWDER = (
    "setblock 4 -60 8 minecraft:stone",
    "setblock 6 -60 8 minecraft:stone",
    "setblock 5 -60 7 minecraft:stone",
    "setblock 5 -60 9 minecraft:stone",
    "setblock 5 -60 8 minecraft:water",
    "setblock 5 -59 8 minecraft:stone",
    "setblock 5 -58 8 minecraft:white_concrete_powder",
)
ANVIL = ("setblock 8 -60 8 minecraft:stone", "setblock 8 -59 8 minecraft:anvil[facing=north]")
ON_TORCH = (
    "setblock 11 -60 8 minecraft:torch",
    "setblock 11 -59 8 minecraft:stone",
    "setblock 11 -58 8 minecraft:sand",
)
ON_SLAB = (
    "setblock 14 -60 8 minecraft:smooth_stone_slab[type=bottom]",
    "setblock 14 -59 8 minecraft:stone",
    "setblock 14 -58 8 minecraft:sand",
)
GRAVITY_RELEASES = (
    ("2 -60 8", 18),
    ("5 -59 8", 8),
    ("8 -60 8", 8),
    ("11 -59 8", 10),
    ("14 -59 8", 9),
)
"""Where each window removes a block, and how many ticks it steps: a block falls on the first
step after the block under it goes, the next one up two steps later, and a fall of one block takes
seven steps (measured on vanilla 26.3)."""


@pytest.mark.asyncio
async def test_gravity_builds_a_column_powder_in_water_an_anvil_and_sand_on_a_torch_and_slab() -> (
    None
):
    first = (await play(GRAVITY)).first

    assert first[len(SETUP) : -5] == (*COLUMN, *POWDER, *ANVIL, *ON_TORCH, *ON_SLAB)


@pytest.mark.asyncio
async def test_gravity_ends_the_windows_with_a_drop_on_its_tick_and_kills_the_item() -> None:
    # The item a falling block breaks into moves at random (the ItemEntity constructor), so the
    # window ends on the tick it appears, and Control kills it before the next window.
    play_ = await play(GRAVITY)

    assert [window.before for window in play_.windows[1:]] == [(), (), (), (KILL_ITEMS,)]
    assert play_.after[:-7] == (KILL_ITEMS,)


@pytest.mark.asyncio
async def test_gravity_compares_the_blocks_the_falling_entities_and_the_landing() -> None:
    windows = (await play(GRAVITY)).windows

    assert {window.label for window in windows} == {GRAVITY_WINDOW}


GRAVITY_WINDOW = (
    f"{OBSERVE_OPEN} minecraft:block_update minecraft:section_blocks_update "
    "minecraft:add_transient_block minecraft:add_entity minecraft:set_entity_data "
    "minecraft:move_entity_pos minecraft:move_entity_pos_rot minecraft:entity_position_sync "
    "minecraft:set_entity_motion minecraft:remove_entities minecraft:level_event "
    "minecraft:sound"
)


def test_gravity_masks_only_how_a_dropped_item_moves_and_faces() -> None:
    masks = GROUPS[GRAVITY].masks

    assert {(mask.packet, mask.path) for mask in masks} == {
        ("minecraft:add_entity", "velocity.x"),
        ("minecraft:add_entity", "velocity.z"),
        ("minecraft:add_entity", "yaw"),
    }


# `blocks/support`

SUPPORT_LAYOUT = (
    "setblock 1 -60 12 minecraft:stone",
    "setblock 1 -59 12 minecraft:torch",
    "setblock 3 -60 12 minecraft:stone",
    "setblock 3 -59 12 minecraft:rail",
    "setblock 5 -60 12 minecraft:stone",
    "setblock 5 -59 12 minecraft:lever[face=floor,facing=north]",
    "setblock 7 -60 12 minecraft:dirt",
    "setblock 7 -59 12 minecraft:poppy",
    "setblock 9 -60 12 minecraft:stone",
    "setblock 9 -59 12 minecraft:oak_door[half=lower,facing=north]",
    "setblock 9 -58 12 minecraft:oak_door[half=upper,facing=north]",
    "setblock 11 -60 12 minecraft:stone",
    "setblock 11 -60 13 minecraft:stone",
    "setblock 11 -59 12 minecraft:red_bed[part=foot,facing=south]",
    "setblock 11 -59 13 minecraft:red_bed[part=head,facing=south]",
    "setblock 13 -59 13 minecraft:stone",
    "setblock 13 -59 12 minecraft:wall_torch[facing=north]",
    "setblock 15 -59 13 minecraft:stone",
    "setblock 15 -59 12 minecraft:ladder[facing=north]",
)
SUPPORT_RELEASES = (
    ("1 -60 12", 1),
    ("3 -60 12", 1),
    ("5 -60 12", 1),
    ("7 -60 12", 1),
    ("9 -60 12", 1),
    ("11 -60 12", 1),
    ("13 -59 13", 1),
    ("15 -59 13", 1),
)
"""A block pops off in the command that removes what holds it (Block.updateOrDestroy): one step
shows that nothing more follows."""


@pytest.mark.asyncio
async def test_support_builds_eight_blocks_each_on_or_against_a_block_of_its_own() -> None:
    first = (await play(SUPPORT)).first

    assert first[len(SETUP) : -5] == SUPPORT_LAYOUT


@pytest.mark.asyncio
async def test_support_kills_the_item_each_window_dropped_before_the_next() -> None:
    # The bed stays: vanilla's bed needs nothing under it.
    play_ = await play(SUPPORT)

    assert [window.before for window in play_.windows[1:]] == [
        (KILL_ITEMS,),
        (KILL_ITEMS,),
        (KILL_ITEMS,),
        (KILL_ITEMS,),
        (KILL_ITEMS,),
        (),
        (KILL_ITEMS,),
    ]
    assert play_.after[:-7] == (KILL_ITEMS,)


@pytest.mark.asyncio
async def test_support_compares_the_blocks_the_drops_and_the_break_particles() -> None:
    windows = (await play(SUPPORT)).windows

    assert {window.label for window in windows} == {SUPPORT_WINDOW}


SUPPORT_WINDOW = (
    f"{OBSERVE_OPEN} minecraft:block_update minecraft:section_blocks_update "
    "minecraft:add_entity minecraft:set_entity_data minecraft:remove_entities "
    "minecraft:level_event minecraft:sound"
)


def test_support_masks_where_a_dropped_item_appears_and_how_it_moves_and_faces() -> None:
    masks = GROUPS[SUPPORT].masks

    assert {(mask.packet, mask.path) for mask in masks} == {
        ("minecraft:add_entity", path)
        for path in ("x", "y", "z", "velocity.x", "velocity.z", "yaw")
    }


RELEASES = {GRAVITY: GRAVITY_RELEASES, SUPPORT: SUPPORT_RELEASES}
CLEARS = {
    GRAVITY: "fill 1 -60 7 15 -53 9 minecraft:air",
    SUPPORT: "fill 1 -60 12 15 -58 13 minecraft:air",
}
