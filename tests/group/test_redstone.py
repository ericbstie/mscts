"""The redstone Groups: what Control builds, places and steps in each window, and what it undoes.

Every test reads one shared play of its Group against a fake server: Control's commands and the
Marks (the Observation windows and the ticks stepped). What a server answers is never asserted:
the fake answers Control's markers and the barrier.
"""

from dataclasses import dataclass
from typing import override

import pytest
from support.control import ControlServer, tree
from support.control_play import Play, replay
from support.gametime import gametime_answer

from mscts.group import GROUPS, GroupKind
from mscts.spec import ServerSpec
from tests.net.fakes import Peer

REPEATER = "redstone/repeater"
COMPARATOR = "redstone/comparator"
TORCH = "redstone/torch"
OBSERVER = "redstone/observer"
DUST = "redstone/dust"
UPDATE_ORDER = "redstone/update-order"
PISTON_PUSH = "redstone/piston-push"
STICKY = "redstone/sticky"
UNMASKED = (REPEATER, COMPARATOR, TORCH, OBSERVER, DUST)
CIRCUIT_IDS = (*UNMASKED, UPDATE_ORDER)
PISTON_IDS = (PISTON_PUSH, STICKY)
GROUP_IDS = (*CIRCUIT_IDS, *PISTON_IDS)
COMMANDS = tree("gamerule", "tp", "tick", "fill", "setblock", "item", "time", "tellraw", "kill")
WINDOW = (
    "observe:open minecraft:block_update minecraft:section_blocks_update minecraft:block_event "
    "minecraft:level_event minecraft:sound"
)
"""The open Mark of every window of a Group without a piston of its own to watch."""
PISTON_WINDOW = (
    f"{WINDOW} minecraft:block_entity_data minecraft:add_entity minecraft:set_entity_data"
)
"""The open Mark of every window of a piston Group: also block entities and dropped items."""
UNDO = (
    "fill 1 -60 1 15 -57 15 minecraft:air strict",
    "fill 1 -60 1 15 -57 15 minecraft:air",
    "gamerule random_tick_speed 3",
    "tp watcher 0.5 -60 0.5",
    "gamerule respawn_radius 10",
    "gamerule player_movement_check true",
    "tick unfreeze",
)
"""What Control undoes after every Group's last window, in order."""
KILL_ITEMS = "kill @e[type=minecraft:item]"

STEP = "tick step 1"
TIME_QUERY = "time query gametime"
FAST_FORWARD = 155
"""The ticks `redstone/torch` steps at once, outside a window."""


@dataclass
class ClockServer(ControlServer):
    """A ControlServer that also answers `time query gametime`.

    Each answer is `FAST_FORWARD` ticks after the last, so a fast-forward has run by the next
    read.
    """

    game_time: int = 0

    @override
    def _answer(self, peer: Peer, command: str) -> bytes:
        if command != TIME_QUERY:
            return super()._answer(peer, command)
        answer = gametime_answer(self.game_time)
        self.game_time += FAST_FORWARD
        return peer.frame("minecraft:system_chat", content=answer, overlay=False)


_PLAYS: dict[str, Play] = {}
"""Each Group's play against a default fake server; no test changes it."""


async def play(group_id: str) -> Play:
    """The play of `group_id` against a default fake server, played the first time it is asked."""
    if group_id not in _PLAYS:
        _PLAYS[group_id] = await replay(group_id, ClockServer(commands=COMMANDS))
    return _PLAYS[group_id]


pytestmark = [pytest.mark.timeout(300), pytest.mark.usefixtures("long_play")]


def steps(ticks: int) -> tuple[str, ...]:
    """`ticks` steps of one tick each."""
    return (STEP,) * ticks


# Every Group


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_each_group_is_registered_tick_exact_with_the_default_spec(group_id: str) -> None:
    group = GROUPS[group_id]
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert group.kind is GroupKind.TICK_EXACT
    assert group.requires == ()
    assert group.spec(default) == default


@pytest.mark.parametrize("group_id", UNMASKED)
def test_each_group_without_a_piston_masks_nothing(group_id: str) -> None:
    assert GROUPS[group_id].masks == ()


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


@pytest.mark.parametrize("group_id", CIRCUIT_IDS)
@pytest.mark.asyncio
async def test_every_window_compares_the_blocks_block_events_world_events_and_sounds(
    group_id: str,
) -> None:
    windows = (await play(group_id)).windows

    assert windows
    assert {window.label for window in windows} == {WINDOW}


@pytest.mark.parametrize("group_id", PISTON_IDS)
@pytest.mark.asyncio
async def test_every_piston_window_also_compares_block_entities_and_dropped_items(
    group_id: str,
) -> None:
    windows = (await play(group_id)).windows

    assert windows
    assert {window.label for window in windows} == {PISTON_WINDOW}


@pytest.mark.parametrize("group_id", [i for i in GROUP_IDS if i != PISTON_PUSH])
@pytest.mark.asyncio
async def test_control_clears_without_updates_first_then_undoes_the_rest(group_id: str) -> None:
    # A plain fill would update a repeater or a torch beside each block it clears, which
    # schedules its tick for the next play: the strict one first (FillCommand, flag 816).
    after = (await play(group_id)).after

    assert after == UNDO


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


# `redstone/torch`


@pytest.mark.asyncio
async def test_torch_builds_two_torches_each_on_a_block_of_stone() -> None:
    first = (await play(TORCH)).first

    assert first[5:] == (
        "setblock 3 -60 3 minecraft:stone",
        "setblock 3 -59 3 minecraft:redstone_torch",
        "setblock 8 -60 8 minecraft:stone",
        "setblock 8 -59 8 minecraft:redstone_torch",
    )


@pytest.mark.asyncio
async def test_torch_powers_the_first_torchs_block_then_takes_the_power_away() -> None:
    inversion = (await play(TORCH)).windows[0]

    assert inversion.commands == (
        "setblock 3 -60 3 minecraft:redstone_block",
        *steps(4),
        "setblock 3 -60 3 minecraft:stone",
        *steps(3),
    )


@pytest.mark.asyncio
async def test_torch_powers_the_second_torchs_block_8_times_every_4_ticks() -> None:
    # The 8th time a torch turns off within 60 ticks, it burns out
    # (`RedstoneTorchBlock.MAX_RECENT_TOGGLES`): it is off 2 ticks after each power. The window
    # ends a tick after the last power goes.
    burnout = (await play(TORCH)).windows[1]
    toggle = (
        "setblock 8 -60 8 minecraft:redstone_block",
        *steps(2),
        "setblock 8 -60 8 minecraft:stone",
        *steps(2),
    )

    assert burnout.commands == (toggle * 8)[:-1]
    assert burnout.ticks == 31


@pytest.mark.asyncio
async def test_torch_fast_forwards_then_steps_until_the_burnt_out_torch_lights_again() -> None:
    # A burnt-out torch ticks again 160 ticks later (`RedstoneTorchBlock.RESTART_DELAY`), on
    # the 4th step after the fast-forward.
    recovery = (await play(TORCH)).windows[2]

    assert recovery.before == (TIME_QUERY, f"tick step {FAST_FORWARD}", TIME_QUERY)
    assert recovery.commands == steps(5)


# `redstone/observer`


@pytest.mark.asyncio
async def test_observer_builds_two_observers_facing_away_from_each_other() -> None:
    first = (await play(OBSERVER)).first

    assert first[5:] == (
        "setblock 3 -60 3 minecraft:observer[facing=west]",
        "setblock 8 -60 8 minecraft:observer[facing=east]",
    )


@pytest.mark.asyncio
async def test_observer_changes_what_one_watches_then_makes_a_clock_of_the_other() -> None:
    # An observer pulses for 2 ticks, 2 ticks after the block it watches changes
    # (`ObserverBlock.startSignal`): a third observer facing the second makes a clock, which
    # stops when it goes.
    (window,) = (await play(OBSERVER)).windows

    assert window.commands == (
        "setblock 2 -60 3 minecraft:stone",
        *steps(6),
        "setblock 2 -60 3 minecraft:air",
        *steps(6),
        "setblock 9 -60 8 minecraft:observer[facing=west]",
        *steps(12),
        "setblock 9 -60 8 minecraft:air",
        *steps(6),
    )
    assert window.ticks == 30


# `redstone/dust`


@pytest.mark.asyncio
async def test_dust_builds_a_line_16_long_and_a_lone_dust() -> None:
    first = (await play(DUST)).first

    assert first[5:] == (
        "fill 2 -60 3 15 -60 3 minecraft:redstone_wire",
        "fill 15 -60 4 15 -60 5 minecraft:redstone_wire",
        "setblock 6 -60 10 minecraft:redstone_wire",
    )


@pytest.mark.asyncio
async def test_dust_powers_the_line_for_a_tick_then_builds_and_cuts_a_climb_a_tick_apart() -> None:
    # Dust changes in the tick its neighbour does: each change shows on the next step.
    (window,) = (await play(DUST)).windows

    assert window.commands == (
        "setblock 1 -60 3 minecraft:redstone_block",
        STEP,
        "setblock 1 -60 3 minecraft:air",
        STEP,
        "setblock 7 -60 10 minecraft:redstone_wire",
        STEP,
        "setblock 7 -60 10 minecraft:stone",
        STEP,
        "setblock 7 -59 10 minecraft:redstone_wire",
        STEP,
        "setblock 6 -59 10 minecraft:stone",
        STEP,
        "setblock 6 -59 10 minecraft:air",
        STEP,
        "setblock 7 -59 10 minecraft:air",
        STEP,
        "setblock 7 -60 10 minecraft:air",
        *steps(2),
    )
    assert window.ticks == 10


# `redstone/update-order`


@pytest.mark.parametrize("group_id", [UPDATE_ORDER, STICKY])
def test_each_group_whose_only_sound_is_a_pistons_masks_only_its_random_pitch(
    group_id: str,
) -> None:
    (mask,) = GROUPS[group_id].masks

    assert (mask.packet, mask.path) == ("minecraft:sound", "pitch")


@pytest.mark.asyncio
async def test_update_order_builds_two_copies_of_dust_between_two_pistons() -> None:
    first = (await play(UPDATE_ORDER)).first
    cross = "redstone_wire[north=side,south=side,east=side,west=side]"
    copies = [
        (
            f"setblock {x} -60 9 minecraft:stone",
            f"setblock {x} -60 11 minecraft:stone",
            f"setblock {x - 1} -60 9 minecraft:piston[facing=south]",
            f"setblock {x - 1} -60 11 minecraft:piston[facing=north]",
            f"setblock {x} -60 10 minecraft:{cross}",
        )
        for x in (5, 10)
    ]

    assert first[5:] == (*copies[0], *copies[1])


@pytest.mark.asyncio
async def test_update_order_powers_and_unpowers_each_copy_5_ticks_apart() -> None:
    # A piston has extended 2 ticks after its block event and retracted 2 ticks after the next:
    # each change waits until the last has ended.
    (window,) = (await play(UPDATE_ORDER)).windows

    assert window.commands == (
        "setblock 5 -59 10 minecraft:redstone_block",
        *steps(5),
        "setblock 10 -59 10 minecraft:redstone_block",
        *steps(5),
        "setblock 5 -59 10 minecraft:air",
        *steps(5),
        "setblock 10 -59 10 minecraft:air",
        *steps(6),
    )
    assert window.ticks == 21


# `redstone/piston-push`

PUSH_ROWS = (1, 3, 5, 7, 8, 9, 11, 13)
"""The z of each piston powered on tick 0; the poppy's, at z 15, is powered on tick 2."""


def east_piston(z: int, ahead: str) -> tuple[str, str]:
    """The `/setblock`s of a piston at x 2, -60, z facing east and of `ahead` at x 3."""
    return (
        f"setblock 2 -60 {z} minecraft:piston[facing=east]",
        f"setblock 3 -60 {z} minecraft:{ahead}",
    )


def behind(z: int, block: str) -> str:
    """The `/setblock` of `block` behind the piston at x 2, -60, z."""
    return f"setblock 1 -60 {z} minecraft:{block}"


def test_piston_push_masks_the_pistons_pitch_and_where_a_dropped_item_appears_and_moves() -> None:
    masks = GROUPS[PISTON_PUSH].masks

    assert [(mask.packet, mask.path) for mask in masks] == [
        ("minecraft:sound", "pitch"),
        *(
            ("minecraft:add_entity", path)
            for path in ("x", "y", "z", "velocity.x", "velocity.z", "yaw")
        ),
    ]


@pytest.mark.asyncio
async def test_piston_push_builds_rows_of_1_12_and_13_stones_blocks_that_stop_and_that_break() -> (
    None
):
    first = (await play(PISTON_PUSH)).first

    assert first[5:] == (
        "fill 3 -60 1 3 -60 1 minecraft:stone",
        "fill 3 -60 3 14 -60 3 minecraft:stone",
        "fill 3 -60 5 15 -60 5 minecraft:stone",
        "setblock 2 -60 1 minecraft:piston[facing=east]",
        "setblock 2 -60 3 minecraft:piston[facing=east]",
        "setblock 2 -60 5 minecraft:piston[facing=east]",
        # The extended piston's power first: placed unpowered, it would retract.
        "setblock 4 -60 11 minecraft:redstone_block",
        *east_piston(7, "obsidian"),
        *east_piston(8, "bedrock"),
        *east_piston(9, "chest"),
        *east_piston(11, "piston[facing=up,extended=true]"),
        "setblock 3 -59 11 minecraft:piston_head[facing=up]",
        *east_piston(13, "torch"),
        *east_piston(15, "poppy"),
    )


@pytest.mark.asyncio
async def test_piston_push_powers_the_pistons_then_the_poppys_and_unpowers_each_4_ticks_later() -> (
    None
):
    # A piston pushes on the next tick and is out 2 ticks later; it retracts likewise. The
    # torch and the poppy break 2 ticks apart, so that each item appears on a tick of its own.
    (window,) = (await play(PISTON_PUSH)).windows

    assert window.commands == (
        *(behind(z, "redstone_block") for z in PUSH_ROWS),
        *steps(2),
        behind(15, "redstone_block"),
        *steps(2),
        *(behind(z, "air") for z in PUSH_ROWS),
        *steps(2),
        behind(15, "air"),
        *steps(4),
    )
    assert window.ticks == 10


@pytest.mark.asyncio
async def test_piston_push_takes_the_dropped_items_away_before_it_clears() -> None:
    after = (await play(PISTON_PUSH)).after

    assert after == (KILL_ITEMS, *UNDO)


# `redstone/sticky`


@pytest.mark.asyncio
async def test_sticky_builds_two_stones_and_a_slime_and_a_honey_block_above_the_grass() -> None:
    # A slime block on the grass would drag the grass along (PistonStructureResolver).
    first = (await play(STICKY)).first
    sticky = "sticky_piston[facing=east]"

    assert first[5:] == (
        f"setblock 2 -60 1 minecraft:{sticky}",
        "setblock 3 -60 1 minecraft:stone",
        f"setblock 2 -60 3 minecraft:{sticky}",
        "setblock 3 -60 3 minecraft:stone",
        f"setblock 2 -59 6 minecraft:{sticky}",
        "setblock 3 -59 6 minecraft:slime_block",
        "setblock 3 -59 7 minecraft:stone",
        "setblock 3 -59 5 minecraft:honey_block",
        f"setblock 2 -59 10 minecraft:{sticky}",
        "setblock 3 -59 10 minecraft:honey_block",
        "setblock 3 -59 11 minecraft:stone",
        "setblock 3 -59 9 minecraft:slime_block",
    )


@pytest.mark.asyncio
async def test_sticky_powers_every_piston_unpowers_one_after_a_tick_and_the_rest_after_5() -> None:
    # A piston whose power goes while its block still moves leaves the block (type 2); the
    # others pull theirs back once in place.
    (window,) = (await play(STICKY)).windows

    assert window.commands == (
        behind(1, "redstone_block"),
        behind(3, "redstone_block"),
        "setblock 1 -59 6 minecraft:redstone_block",
        "setblock 1 -59 10 minecraft:redstone_block",
        STEP,
        behind(3, "air"),
        *steps(4),
        behind(1, "air"),
        "setblock 1 -59 6 minecraft:air",
        "setblock 1 -59 10 minecraft:air",
        *steps(4),
    )
    assert window.ticks == 9
