"""The redstone Groups: what Control builds, places and steps in each window, and what it undoes.

Every test reads one shared play of its Group against a fake server: Control's commands and the
Marks (the Observation windows and the ticks stepped). What a server answers is never asserted:
the fake answers Control's markers and the barrier.
"""

import pytest

from mscts.group import GROUPS, GroupKind
from mscts.spec import ServerSpec
from mscts.transcript import Transcript
from tests.group import test_control
from tests.group.test_control import ControlServer, playing, tree
from tests.group.test_entities_items import Play, read

REPEATER = "redstone/repeater"
COMPARATOR = "redstone/comparator"
GROUP_IDS = (REPEATER, COMPARATOR)
COMMANDS = tree("gamerule", "tp", "tick", "fill", "setblock", "item", "tellraw")
WINDOW = (
    "observe:open minecraft:block_update minecraft:section_blocks_update minecraft:block_event "
    "minecraft:level_event minecraft:sound"
)
"""The open Mark of every window."""

STEP = "tick step 1"


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


def steps(ticks: int) -> tuple[str, ...]:
    """`ticks` steps of one tick each."""
    return (STEP,) * ticks


# Every Group


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_each_group_is_registered_tick_exact_with_the_default_spec_and_no_mask(
    group_id: str,
) -> None:
    group = GROUPS[group_id]
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert group.kind is GroupKind.TICK_EXACT
    assert group.requires == ()
    assert group.masks == ()
    assert group.spec(default) == default


@pytest.mark.parametrize("group_id", GROUP_IDS)
@pytest.mark.asyncio
async def test_control_pins_the_join_stops_random_ticks_and_freezes_before_it_builds(
    group_id: str,
) -> None:
    first = (await play(group_id)).first

    assert first[:5] == (
        "gamerule player_movement_check false",
        "gamerule respawn_radius 0",
        "tp control 96.5 -60 96.5",
        "gamerule random_tick_speed 0",
        "tick freeze",
    )


@pytest.mark.parametrize("group_id", GROUP_IDS)
@pytest.mark.asyncio
async def test_every_window_compares_the_blocks_block_events_world_events_and_sounds(
    group_id: str,
) -> None:
    windows = (await play(group_id)).windows

    assert windows
    assert {window.label for window in windows} == {WINDOW}


@pytest.mark.parametrize("group_id", GROUP_IDS)
@pytest.mark.asyncio
async def test_control_clears_without_updates_first_then_undoes_the_rest(group_id: str) -> None:
    # A plain fill would update a repeater or a torch beside each block it clears, which
    # schedules its tick for the next play: the strict one first (FillCommand, flag 816).
    after = (await play(group_id)).after

    assert after == (
        "fill 1 -60 1 15 -57 15 minecraft:air strict",
        "fill 1 -60 1 15 -57 15 minecraft:air",
        "gamerule random_tick_speed 3",
        "tp watcher 0.5 -60 0.5",
        "gamerule respawn_radius 10",
        "gamerule player_movement_check true",
        "tick unfreeze",
    )


# `redstone/repeater`


@pytest.mark.asyncio
async def test_repeater_builds_four_delays_a_locked_repeater_and_one_for_a_pulse() -> None:
    first = (await play(REPEATER)).first

    assert first[5:] == (
        "setblock 3 -60 2 minecraft:repeater[facing=west,delay=1]",
        "setblock 3 -60 4 minecraft:repeater[facing=west,delay=2]",
        "setblock 3 -60 6 minecraft:repeater[facing=west,delay=3]",
        "setblock 3 -60 8 minecraft:repeater[facing=west,delay=4]",
        "setblock 3 -60 12 minecraft:redstone_block",
        "setblock 3 -60 11 minecraft:repeater[facing=south,powered=true]",
        "setblock 3 -60 10 minecraft:repeater[facing=west,locked=true]",
        "setblock 3 -60 14 minecraft:repeater[facing=west,delay=4]",
    )


@pytest.mark.asyncio
async def test_repeater_powers_every_input_feeds_a_1_tick_pulse_then_unlocks_and_unpowers() -> None:
    # A repeater switches delay times 2 ticks after its input (RepeaterBlock.getDelay): the
    # last are off on tick 18. The pulse's input goes after one tick; the lock's at tick 10.
    (window,) = (await play(REPEATER)).windows

    assert window.commands == (
        "setblock 2 -60 2 minecraft:redstone_block",
        "setblock 2 -60 4 minecraft:redstone_block",
        "setblock 2 -60 6 minecraft:redstone_block",
        "setblock 2 -60 8 minecraft:redstone_block",
        "setblock 2 -60 10 minecraft:redstone_block",
        "setblock 2 -60 14 minecraft:redstone_block",
        STEP,
        "setblock 2 -60 14 minecraft:air",
        *steps(9),
        "setblock 2 -60 2 minecraft:air",
        "setblock 2 -60 4 minecraft:air",
        "setblock 2 -60 6 minecraft:air",
        "setblock 2 -60 8 minecraft:air",
        "setblock 3 -60 12 minecraft:air",
        *steps(6),
        "setblock 2 -60 10 minecraft:air",
        *steps(3),
    )
    assert window.ticks == 19


# `redstone/comparator`


@pytest.mark.asyncio
async def test_comparator_builds_a_compare_and_a_subtract_case_and_one_that_reads_a_chest() -> None:
    first = (await play(COMPARATOR)).first

    assert first[5:] == (
        "setblock 3 -60 1 minecraft:redstone_block",
        "setblock 3 -60 2 minecraft:redstone_wire",
        "setblock 3 -60 3 minecraft:redstone_wire",
        "setblock 3 -60 4 minecraft:comparator[facing=west,mode=compare]",
        "fill 4 -60 4 6 -60 4 minecraft:redstone_wire",
        "setblock 3 -60 11 minecraft:redstone_block",
        "setblock 3 -60 10 minecraft:redstone_wire",
        "setblock 3 -60 9 minecraft:redstone_wire",
        "setblock 3 -60 8 minecraft:comparator[facing=west,mode=subtract]",
        "fill 4 -60 8 6 -60 8 minecraft:redstone_wire",
        "setblock 2 -60 13 minecraft:chest",
        "setblock 3 -60 13 minecraft:comparator[facing=west,mode=compare]",
        "fill 4 -60 13 6 -60 13 minecraft:redstone_wire",
    )


@pytest.mark.asyncio
async def test_comparator_feeds_the_rears_removes_the_sides_then_fills_and_empties_the_chest() -> (
    None
):
    # A comparator switches 2 ticks after its inputs (ComparatorBlock.getDelay): each change
    # comes 4 ticks after the last, and the chest's comparator is off on tick 18.
    (window,) = (await play(COMPARATOR)).windows
    stone = "with minecraft:stone 64"

    assert window.commands == (
        "setblock 2 -60 4 minecraft:redstone_block",
        "setblock 2 -60 8 minecraft:redstone_block",
        *steps(4),
        "setblock 3 -60 1 minecraft:air",
        "setblock 3 -60 11 minecraft:air",
        *steps(4),
        f"item replace block 2 -60 13 container.0 {stone}",
        *steps(4),
        f"item replace block 2 -60 13 container.1 {stone}",
        f"item replace block 2 -60 13 container.2 {stone}",
        f"item replace block 2 -60 13 container.3 {stone}",
        *steps(4),
        "item replace block 2 -60 13 container.0 with minecraft:air",
        "item replace block 2 -60 13 container.1 with minecraft:air",
        "item replace block 2 -60 13 container.2 with minecraft:air",
        "item replace block 2 -60 13 container.3 with minecraft:air",
        *steps(3),
    )
    assert window.ticks == 19
