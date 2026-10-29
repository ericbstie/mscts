"""The entity activation Groups: what Control sets up, summons and steps, and what it undoes.

Every test reads one shared play of its Group against a fake server: Control's commands and the
Marks (the Observation windows and the ticks stepped). What a server answers is never asserted:
the fake answers Control's markers, the barrier and the game time, and sends the watcher the
chunks west of the spawn as it joins.
"""

from dataclasses import dataclass
from typing import override

import pytest
from support.control import ControlServer, playing, tree
from support.control_play import Play, read, replay
from support.gametime import gametime_answer

import mscts.groups
from mscts.group import GROUPS, GroupKind
from mscts.groups import entities_activation
from mscts.spec import ServerSpec
from mscts.transcript import Transcript
from tests.net.fakes import EMPTY_CHUNK, JoinScript, Peer, join_server

FALLING = "entities/activation-falling"
ITEMS = "entities/activation-items"
EDGE = "entities/activation-edge"
GROUP_IDS = (FALLING, ITEMS, EDGE)
COMMANDS = tree(
    "gamerule", "weather", "tp", "tick", "summon", "kill", "fill", "setblock", "time", "tellraw"
)
TAG = "mscts_activation"
STEP = "tick step 1"
TIME_QUERY = "time query gametime"

MOVES = (
    "minecraft:bundle_delimiter",
    "minecraft:add_entity",
    "minecraft:set_entity_data",
    "minecraft:set_entity_motion",
    "minecraft:entity_position_sync",
    "minecraft:remove_entities",
)
HURTS = (
    "minecraft:bundle_delimiter",
    "minecraft:add_entity",
    "minecraft:set_entity_data",
    "minecraft:damage_event",
    "minecraft:entity_event",
    "minecraft:hurt_animation",
)
MOVES_LABEL = f"observe:open {' '.join(MOVES)}"
HURTS_LABEL = f"observe:open {' '.join(HURTS)}"

PINNED = (
    "gamerule player_movement_check false",
    "gamerule respawn_radius 0",
    "gamerule advance_weather false",
    "weather clear",
    TIME_QUERY,
    TIME_QUERY,
    "tp control 96.5 -60 96.5",
)
"""What Control runs before the watcher joins, in order: the joins pinned, the weather cleared
and left to fade while the world still runs, and Control sent away."""

CLEAR = (
    f"tp @e[tag={TAG}] 0.5 -60 12.5",
    f"kill @e[tag={TAG}]",
    "kill @e[type=minecraft:item]",
    "gamerule mob_drops false",
    f"kill @e[tag={TAG}]",
    "gamerule mob_drops true",
    "tick unfreeze",
    "gamerule advance_weather true",
    "gamerule respawn_radius 10",
    "gamerule player_movement_check true",
)
"""What Control runs after the last window, in order: the tagged entities come into the watcher's
simulation distance and go, with what they dropped, then the weather cycle and the rules come
back."""

HELD = tuple((x, 0) for x in range(-5, 1))
"""The chunks the watcher must hold before anything is summoned: the spawn's and five west."""

DISTANCES = (8, 24, 40, 56)


def steps(ticks: int) -> tuple[str, ...]:
    """`ticks` steps of one tick each."""
    return (STEP,) * ticks


def summoned(entity: str, at: tuple[float, float, float], *nbt: str) -> str:
    """The `/summon` of `entity` at `at` with `nbt`, facing west and tagged."""
    x, y, z = at
    fields = ",".join((*nbt, "Rotation:[90f,0f]", f'Tags:["{TAG}"]'))
    return f"summon minecraft:{entity} {x} {y} {z} {{{fields}}}"


def _chunks(at: tuple[tuple[int, int], ...]) -> list[dict[str, object]]:
    """Empty chunks at each of `at`."""
    return [{**EMPTY_CHUNK, "chunk_x": x, "chunk_z": z} for x, z in at]


@dataclass
class ActivationServer(ControlServer):
    """A ControlServer that sends the chunks in `held` as a joining Bot's first batch.

    The watcher is sent the chunks in `late` right after its join, unread until it next reads.
    It also answers `time query gametime`, each answer 100 ticks after the last, so a
    fast-forward has run by the next read.
    """

    held: tuple[tuple[int, int], ...] = HELD
    late: tuple[tuple[int, int], ...] = ()
    game_time: int = 0

    @override
    async def __call__(self, peer: Peer) -> None:
        script = JoinScript(commands=COMMANDS, first_batch=_chunks(self.held), then=self._play)
        await join_server(self.seen, script)(peer)

    @override
    async def _play(self, peer: Peer) -> None:
        if peer.name == "watcher":
            for chunk in _chunks(self.late):
                await peer.send("minecraft:level_chunk_with_light", **chunk)
        await super()._play(peer)

    @override
    def _answer(self, peer: Peer, command: str) -> bytes:
        if command != TIME_QUERY:
            return super()._answer(peer, command)
        answer = gametime_answer(self.game_time)
        self.game_time += 100
        return peer.frame("minecraft:system_chat", content=answer, overlay=False)


_PLAYS: dict[str, Play] = {}
"""Each Group's play against a default fake server; no test changes it."""


async def play(group_id: str) -> Play:
    """The play of `group_id` against a default fake server, played the first time it is asked."""
    if group_id not in _PLAYS:
        _PLAYS[group_id] = await replay(group_id, ActivationServer())
    return _PLAYS[group_id]


# Every Group


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_each_group_is_tick_exact_with_view_distance_10_and_simulation_distance_4(
    group_id: str,
) -> None:
    group = GROUPS[group_id]
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert group.kind is GroupKind.TICK_EXACT
    assert group.requires == ()
    assert group.masks == ()
    assert group.spec(default) == ServerSpec(
        host="127.0.0.1", port=25566, view_distance=10, simulation_distance=4
    )


def test_the_groups_package_imports_the_module_so_that_every_run_has_its_groups() -> None:
    assert "entities_activation" in mscts.groups.__all__
    assert mscts.groups.entities_activation is entities_activation


def test_the_windows_compare_how_entities_appear_move_and_are_hurt() -> None:
    assert entities_activation.MOVES == MOVES
    assert entities_activation.HURTS == HURTS


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_control_pins_the_join_and_goes_away_before_anything_else(group_id: str) -> None:
    result = await play(group_id)

    assert result.first[: len(PINNED)] == PINNED


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_the_tagged_entities_and_their_drops_go_and_the_rules_come_back_last(
    group_id: str,
) -> None:
    result = await play(group_id)

    assert result.after[-len(CLEAR) - 1 :] == (*CLEAR, "tick unfreeze")


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_every_window_steps_twenty_ticks(group_id: str) -> None:
    result = await play(group_id)

    assert result.windows
    assert all(window.ticks == 20 for window in result.windows)


@pytest.mark.asyncio
async def test_a_chunk_that_never_comes_ends_the_play_before_anything_is_summoned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(entities_activation, "_CHUNK_SYNCS", 3)
    server = ActivationServer(held=HELD[1:])
    transcript = Transcript(group_id=FALLING, server="fake")

    with pytest.raises(TimeoutError, match=r"watcher still lacked chunks \[\(-5, 0\)\]"):
        await _play_into(transcript, server)

    sent = read(transcript)
    assert sent.windows == ()
    assert sent.after == (*PINNED, *CLEAR)


@pytest.mark.asyncio
async def test_the_watcher_reads_on_until_a_chunk_sent_after_its_join_has_come(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(entities_activation, "_CHUNK_SYNCS", 3)

    result = await replay(FALLING, ActivationServer(held=HELD[1:], late=HELD[:1]))

    assert len(result.windows) == 2


async def _play_into(transcript: Transcript, server: ActivationServer) -> None:
    async with playing(server, transcript) as context:
        await GROUPS[FALLING].run(context)


# `entities/activation-falling`


@pytest.mark.asyncio
async def test_falling_freezes_the_world_once_the_watcher_holds_its_chunks_and_builds_nothing() -> (
    None
):
    result = await play(FALLING)

    assert result.first == (*PINNED, "tick freeze")
    assert result.after == (*CLEAR, "tick unfreeze")


@pytest.mark.asyncio
async def test_falling_summons_four_armor_stands_two_blocks_up_then_steps_them_to_the_ground() -> (
    None
):
    result = await play(FALLING)
    stands = tuple(summoned("armor_stand", (0.5 - d, -58.0, 0.5)) for d in DISTANCES)

    assert result.windows[0].label == MOVES_LABEL
    assert result.windows[0].commands == (*stands, *steps(20))


@pytest.mark.asyncio
async def test_falling_then_drops_four_pigs_five_blocks_and_compares_their_fall_damage() -> None:
    result = await play(FALLING)
    pigs = tuple(
        summoned("pig", (0.5 - d, -55.0, 2.5), "PersistenceRequired:1b") for d in DISTANCES
    )

    assert result.windows[1].label == HURTS_LABEL
    assert result.windows[1].before == ()
    assert result.windows[1].commands == (*pigs, *steps(20))
    assert len(result.windows) == 2


# `entities/activation-items`


def trench(distance: int) -> str:
    """The 9 blocks of ground a stream of the item at `distance` runs west in."""
    return f"fill {-distance - 8} -61 8 {-distance} -61 8"


BUILD = tuple(
    command
    for d in DISTANCES
    for command in (f"{trench(d)} minecraft:air", f"setblock {-d} -61 8 minecraft:water")
)
"""A trench with water at its east end for each distance, in order."""

FAST_FORWARD = (TIME_QUERY, "tick step 60", TIME_QUERY)
"""Control steps 60 ticks at once, so the water has run to the west end of each trench."""


def stack(item: str) -> str:
    """The `Item` field of one `item` (without `minecraft:`)."""
    return f'Item:{{id:"minecraft:{item}",count:1}}'


UNBUILD = tuple(f"{trench(d)} minecraft:grass_block" for d in reversed(DISTANCES))


@pytest.mark.asyncio
async def test_items_digs_streams_then_freezes_and_lets_the_water_run() -> None:
    result = await play(ITEMS)

    assert result.first == (*PINNED, *BUILD, "tick freeze", *FAST_FORWARD)


@pytest.mark.asyncio
async def test_items_drops_an_item_in_each_stream_and_slides_none_on_ice() -> None:
    result = await play(ITEMS)
    in_streams = tuple(
        summoned("item", (0.5 - d, -61.0, 8.5), stack(item), "Motion:[0.0d,0.0d,0.0d]")
        for d, item in zip(DISTANCES, ("sand", "gravel", "glass", "bricks"), strict=True)
    )

    assert [window.label for window in result.windows] == [MOVES_LABEL]
    assert result.windows[0].commands == (*in_streams, *steps(20))


@pytest.mark.asyncio
async def test_items_takes_the_streams_away_before_the_items() -> None:
    result = await play(ITEMS)

    assert result.after == (*UNBUILD, *CLEAR, "tick unfreeze")


# `entities/activation-edge`


def chunk_x(x: float) -> int:
    """The chunk x of the block column at `x`."""
    return int(x // 16)


@pytest.mark.asyncio
async def test_edge_summons_a_stand_in_the_last_chunk_inside_and_one_in_the_first_outside() -> None:
    result = await play(EDGE)
    inside, outside = (-63.5, -58.0, 4.5), (-64.5, -58.0, 6.5)

    assert (chunk_x(inside[0]), chunk_x(outside[0])) == (-4, -5)
    assert result.first == (*PINNED, "tick freeze")
    assert [window.label for window in result.windows] == [MOVES_LABEL]
    assert result.windows[0].commands == (
        summoned("armor_stand", inside),
        summoned("armor_stand", outside),
        *steps(20),
    )
    assert result.after == (*CLEAR, "tick unfreeze")
