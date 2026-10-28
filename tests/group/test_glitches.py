"""The glitch Groups: what Control builds, places and steps in each window, and what it undoes.

Every test reads one shared play of its Group against a fake server: Control's commands and the
Marks (the Observation windows and the ticks stepped). What a server answers is never asserted:
the fake answers Control's markers, the barrier and the game time.
"""

from dataclasses import dataclass
from typing import override

import pytest
from support.control import ControlServer, tree
from support.control_play import Play, replay
from support.gametime import gametime_answer
from support.player_server import FADE_READS, FADE_TICKS, TIME_QUERY

from mscts.group import GROUPS, GroupKind
from mscts.spec import ServerSpec
from tests.net.fakes import Peer

BEDROCK = "glitches/bedrock-breaking"
TNT = "glitches/tnt-duplication"
GROUP_IDS = (BEDROCK, TNT)
COMMANDS = tree(
    "gamerule", "weather", "time", "tp", "tick", "fill", "setblock", "summon", "kill", "tellraw"
)
WINDOW = (
    "observe:open minecraft:block_update minecraft:section_blocks_update minecraft:block_event "
    "minecraft:level_event minecraft:sound minecraft:explode minecraft:add_entity "
    "minecraft:remove_entities minecraft:set_entity_data"
)
"""The open Mark of every window: the blocks, the pistons, the explosions and the entities."""
SET_UP = (
    "gamerule advance_weather false",
    "weather clear",
    *FADE_READS,
    "gamerule player_movement_check false",
    "gamerule respawn_radius 0",
    "tp control 96.5 -60 96.5",
    "gamerule random_tick_speed 0",
    "tick freeze",
)
"""What Control does before it builds: the weather first, while the world still runs."""
CLEAR = "fill 3 -60 3 25 -43 29 minecraft:air"
UNDO = (
    "fill 1 -60 1 15 -57 15 minecraft:air strict",
    "fill 1 -60 1 15 -57 15 minecraft:air",
    "gamerule random_tick_speed 3",
    "tp watcher 0.5 -60 0.5",
    "gamerule respawn_radius 10",
    "gamerule player_movement_check true",
    "kill @e[type=minecraft:tnt]",
    "kill @e[type=minecraft:item]",
    f"{CLEAR} strict",
    CLEAR,
    "gamerule advance_weather true",
    "tick unfreeze",
)
"""What Control undoes after every Group's last window, in order: the redstone arena's undo,
then the machines and what they made, then the weather."""

STEP = "tick step 1"


@dataclass
class ClockServer(ControlServer):
    """A ControlServer that also answers `time query gametime`.

    Each answer is `FADE_TICKS` ticks after the last, so a storm has faded, and a fast-forward
    has run, by the next read.
    """

    game_time: int = 0

    @override
    def _answer(self, peer: Peer, command: str) -> bytes:
        if command != TIME_QUERY:
            return super()._answer(peer, command)
        answer = gametime_answer(self.game_time)
        self.game_time += FADE_TICKS
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


def masked(group_id: str) -> list[tuple[str, str]]:
    """The packet and path of each Mask of `group_id`, in order."""
    return [(mask.packet, mask.path) for mask in GROUPS[group_id].masks]


DROPPED_ITEM = [
    ("minecraft:add_entity", path) for path in ("x", "y", "z", "velocity.x", "velocity.z", "yaw")
]
"""What `blocks.DROP_MASKS` hides: where a dropped item appears, and how it moves and faces."""


# Every Group


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_each_group_is_tick_exact_with_the_default_spec_and_requires_the_piston_groups(
    group_id: str,
) -> None:
    group = GROUPS[group_id]
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert group.kind is GroupKind.TICK_EXACT
    assert group.requires == ("redstone/piston-push", "redstone/sticky")
    assert group.spec(default) == default


@pytest.mark.parametrize("group_id", GROUP_IDS)
@pytest.mark.asyncio
async def test_control_calms_the_weather_then_sets_up_the_redstone_arena(group_id: str) -> None:
    # A storm on one Instance only can strike lightning, an `add_entity`, in a window: the
    # weather is cleared and left to fade while the world still runs (#426).
    first = (await play(group_id)).first

    assert first[: len(SET_UP)] == SET_UP


@pytest.mark.parametrize("group_id", GROUP_IDS)
@pytest.mark.asyncio
async def test_every_window_compares_blocks_pistons_explosions_and_entities(
    group_id: str,
) -> None:
    windows = (await play(group_id)).windows

    assert windows
    assert {window.label for window in windows} == {WINDOW}


@pytest.mark.parametrize("group_id", GROUP_IDS)
@pytest.mark.asyncio
async def test_control_kills_what_the_machines_made_then_clears_them_without_updates_first(
    group_id: str,
) -> None:
    after = (await play(group_id)).after

    assert after == UNDO


# `glitches/bedrock-breaking`


def breaker(z: int, target: str) -> tuple[str, ...]:
    """The `/setblock`s of one machine: `target` at x 12, -53, z and the lever in its box."""
    return (
        f"fill 8 -53 {z - 1} 11 -51 {z + 1} minecraft:obsidian",
        f"setblock 9 -52 {z} minecraft:air",
        f"setblock 12 -53 {z} minecraft:{target}",
        f"setblock 12 -51 {z} minecraft:obsidian",
        f"setblock 10 -52 {z} minecraft:lever[face=wall,facing=west,powered=true]",
    )


def test_bedrock_breaking_masks_the_pistons_pitch_and_where_the_lever_item_appears_and_moves() -> (
    None
):
    assert masked(BEDROCK) == [("minecraft:sound", "pitch"), *DROPPED_ITEM]


@pytest.mark.asyncio
async def test_bedrock_breaking_builds_a_bedrock_and_an_end_portal_frame_each_by_a_lever() -> None:
    first = (await play(BEDROCK)).first

    assert first[len(SET_UP) :] == (*breaker(12, "bedrock"), *breaker(4, "end_portal_frame"))


@pytest.mark.parametrize(("window", "z"), [(0, 12), (1, 4)])
@pytest.mark.asyncio
async def test_bedrock_breaking_places_the_piston_blows_up_the_lever_and_turns_the_piston_down(
    window: int, z: int
) -> None:
    # The piston extends on tick 1. The TNT, summoned on tick 4 with a fuse of 1, blows up the
    # lever on tick 5; the piston then retracts on tick 6, in the direction it faces by then
    # (`PistonBaseBlock.triggerEvent`), and removes the block below. It lands on tick 8.
    stepped = (await play(BEDROCK)).windows[window]

    assert stepped.commands == (
        f"setblock 12 -52 {z} minecraft:piston[facing=east]",
        *steps(4),
        f"summon minecraft:tnt 9.5 -52 {z}.5 {{fuse:1s,NoGravity:1b}}",
        STEP,
        f"setblock 12 -52 {z} minecraft:piston[facing=down]",
        *steps(4),
    )
    assert stepped.ticks == 9


# `glitches/tnt-duplication`


def test_tnt_duplication_masks_only_the_random_push_of_the_primed_tnt_and_where_it_explodes() -> (
    None
):
    # PrimedTnt.<init> pushes it 0.02 a tick in a random direction: x and z of its motion and of
    # the explosion's centre. No item drops in its windows, so DROP_MASKS is not needed.
    assert masked(TNT) == [
        ("minecraft:add_entity", "velocity.x"),
        ("minecraft:add_entity", "velocity.z"),
        ("minecraft:explode", "center.x"),
        ("minecraft:explode", "center.z"),
    ]


@pytest.mark.asyncio
async def test_tnt_duplication_builds_a_pool_and_a_sticky_piston_that_pushes_a_tnt_on_slime() -> (
    None
):
    first = (await play(TNT)).first

    assert first[len(SET_UP) :] == (
        "fill 19 -60 5 25 -60 11 minecraft:glass",
        "fill 20 -60 6 24 -60 10 minecraft:water",
        "setblock 20 -45 9 minecraft:sticky_piston[facing=east]",
        "setblock 21 -45 9 minecraft:stone",
        "setblock 22 -45 9 minecraft:slime_block",
        "setblock 21 -45 8 minecraft:dead_tube_coral_wall_fan[facing=north,waterlogged=false]",
        "setblock 22 -45 8 minecraft:tnt",
        # Strict, or its update would prime the TNT under it.
        "setblock 22 -44 8 minecraft:redstone_block strict",
    )


@pytest.mark.asyncio
async def test_tnt_duplication_powers_the_piston_then_fast_forwards_to_the_explosion() -> None:
    # The TNT is primed on tick 1 with a fuse of 80 and explodes on tick 80: 6 ticks, 70 at once
    # outside any window, then the explosion on the 4th of 10 more.
    pushed, exploded = (await play(TNT)).windows

    assert pushed.commands == ("setblock 19 -45 9 minecraft:redstone_block", *steps(6))
    assert pushed.ticks == 6
    assert exploded.before == (TIME_QUERY, "tick step 70", TIME_QUERY)
    assert exploded.commands == steps(10)
