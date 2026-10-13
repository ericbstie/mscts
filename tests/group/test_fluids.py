"""The fluid Groups: what Control builds, places and steps in each window, and what it undoes.

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

WATER_SPREAD = "fluids/water-spread"
GROUP_IDS = (WATER_SPREAD,)
SETTING_NO_RULE = (WATER_SPREAD,)
"""The Groups that change no game rule but random ticks."""
COMMANDS = tree("gamerule", "tp", "tick", "fill", "setblock", "tellraw")
WINDOW = (
    "observe:open minecraft:block_update minecraft:section_blocks_update minecraft:level_event "
    "minecraft:sound"
)
"""The open Mark of every window."""

STEP = "tick step 1"
FLOOR = "fill 0 -61 0 15 -61 15 minecraft:stone"


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
async def test_control_pins_the_join_stops_random_ticks_and_lays_a_stone_floor_first(
    group_id: str,
) -> None:
    first = (await play(group_id)).first

    assert first[:5] == (
        "gamerule player_movement_check false",
        "gamerule respawn_radius 0",
        "tp control 96.5 -60 96.5",
        "gamerule random_tick_speed 0",
        FLOOR,
    )


@pytest.mark.parametrize("group_id", GROUP_IDS)
@pytest.mark.asyncio
async def test_control_freezes_the_world_last_before_the_window(group_id: str) -> None:
    first = (await play(group_id)).first

    assert first[-1] == "tick freeze"


@pytest.mark.parametrize("group_id", GROUP_IDS)
@pytest.mark.asyncio
async def test_each_group_has_one_window_of_the_blocks_the_fizz_and_the_sounds(
    group_id: str,
) -> None:
    (window,) = (await play(group_id)).windows

    assert window.label == WINDOW


@pytest.mark.parametrize("group_id", GROUP_IDS)
@pytest.mark.asyncio
async def test_control_clears_the_floor_puts_the_grass_back_and_undoes_the_rest(
    group_id: str,
) -> None:
    after = (await play(group_id)).after

    # A plain fill would update the shape of a source beside each block it clears, which
    # schedules the source's tick: the strict one first (FillCommand, flag 816).
    assert after[:7] == (
        "fill 0 -60 0 15 -59 15 minecraft:air strict",
        "fill 0 -60 0 15 -59 15 minecraft:air",
        "fill 0 -61 0 15 -61 15 minecraft:grass_block",
        "gamerule random_tick_speed 3",
        "tp watcher 0.5 -60 0.5",
        "gamerule respawn_radius 10",
        "gamerule player_movement_check true",
    )
    assert after[-1] == "tick unfreeze"


@pytest.mark.parametrize("group_id", SETTING_NO_RULE)
@pytest.mark.asyncio
async def test_a_group_that_sets_no_rule_undoes_nothing_more(group_id: str) -> None:
    assert len((await play(group_id)).after) == 8


# `fluids/water-spread`


@pytest.mark.asyncio
async def test_water_spread_digs_a_hole_in_the_floor_at_its_east_edge() -> None:
    first = (await play(WATER_SPREAD)).first

    assert first[5:-1] == ("setblock 15 -61 14 minecraft:air",)


@pytest.mark.asyncio
async def test_water_spread_places_a_source_in_the_middle_then_one_3_blocks_from_the_hole() -> None:
    # Water spreads a block every 5 ticks, up to 7 blocks (WaterFluid.getTickDelay,
    # getDropOff): the middle source's last block changes on tick 35.
    (window,) = (await play(WATER_SPREAD)).windows

    assert window.commands == (
        "setblock 8 -60 8 minecraft:water",
        STEP,
        "setblock 12 -60 14 minecraft:water",
        *(STEP,) * 35,
    )
    assert window.ticks == 36
