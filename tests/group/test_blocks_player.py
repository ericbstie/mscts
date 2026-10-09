"""The blocks Groups for a player: what the digger sends in each window, and what is undone after.

Every test plays a Group against a fake server and reads the Transcript for what the Bots sent
(the digger's actions, Control's commands) and the Marks (the Observation windows and the
ticks stepped). What a server answers is never asserted: the fake only answers the barrier and
Control's markers.
"""

import asyncio
from dataclasses import dataclass, replace

import pytest

from mscts.bot import Face
from mscts.codec.packets import Direction
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN, TICK_MARK
from mscts.group import GROUPS, GroupKind
from mscts.groups import blocks, blocks_player
from mscts.spec import GameMode, ServerSpec
from mscts.transcript import Transcript
from tests.group import test_control
from tests.group.test_control import CHAT_COMMAND, MARKER, ControlServer, playing, tree

PLAYER_ACTION, USE_ITEM_ON = "minecraft:player_action", "minecraft:use_item_on"
MOVE_ROT = "minecraft:move_player_rot"
START, STOP = 0, 3
COMMANDS = tree("setblock", "fill", "tp", "tick", "gamerule", "kill", "item", "summon", "tellraw")
DIG_IDS = ("blocks/dig-survival", "blocks/dig-creative")
GROUP_IDS = (*DIG_IDS, "blocks/place")
UNDO = ("gamerule random_tick_speed 3",)
"""What Control pushes first among its undos, so it runs last of the ones these tests read."""


@dataclass(frozen=True)
class Window:
    """One Observation window: what Control set before it, what the digger sent, ticks stepped."""

    before: tuple[str, ...]
    sent: tuple[tuple[str, dict[str, object]], ...]
    ticks: int


@dataclass(frozen=True)
class Play:
    """A played Group: its windows, and Control's commands after the last one."""

    windows: tuple[Window, ...]
    after: tuple[str, ...]
    commands: tuple[str, ...]


def control_commands(transcript: Transcript) -> list[tuple[int, str]]:
    """Control's commands with when, but its markers."""
    commands = [
        (event.t_ns, str((event.packet.fields or {})["command"]))
        for event in transcript.events
        if event.bot == "control"
        and event.packet.direction is Direction.SERVERBOUND
        and event.packet.name == CHAT_COMMAND
    ]
    return [(t_ns, command) for t_ns, command in commands if not command.startswith(MARKER)]


def read(transcript: Transcript) -> Play:
    """The windows of `transcript` (each opened and closed at the digger) and what follows."""
    opens = [mark.t_ns for mark in transcript.marks if mark.label.startswith(OBSERVE_OPEN)]
    closes = [
        mark.t_ns
        for mark in transcript.marks
        if mark.label == f"{OBSERVE_CLOSE} {blocks_player.DIGGER}"
    ]
    assert len(opens) == len(closes), transcript.marks
    ticks = [
        m.t_ns for m in transcript.marks if m.label.startswith(TICK_MARK) and " " not in m.label
    ]
    actions = [
        (event.t_ns, event.packet.name, dict(event.packet.fields or {}))
        for event in transcript.events
        if event.bot == blocks_player.DIGGER and event.packet.direction is Direction.SERVERBOUND
    ]
    control = control_commands(transcript)
    windows, previous = [], 0
    for opened, closed in zip(opens, closes, strict=True):
        windows.append(
            Window(
                before=tuple(c for t, c in control if previous <= t < opened),
                sent=tuple(
                    (name, fields)
                    for t, name, fields in actions
                    if opened <= t <= closed and name in {PLAYER_ACTION, USE_ITEM_ON}
                ),
                ticks=sum(opened <= t <= closed for t in ticks),
            )
        )
        previous = closed
    return Play(
        tuple(windows),
        tuple(c for t, c in control if t > previous),
        tuple(c for _, c in control),
    )


pytestmark = pytest.mark.timeout(300)
"""A play of `blocks/place` takes about 70 s against the fake, more under load."""


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    """Take the clock out of the survival digs: they wait 8 s and about 10 s more, by the clock."""
    for name in ("TICK_S", "SETTLE_S", "UPTIME_S"):
        monkeypatch.setattr(blocks_player, name, 0.0)
    monkeypatch.setattr(test_control, "PLAY_TIMEOUT_S", 280.0)


_PLAYS: dict[str, Play] = {}
"""What each Group sent, kept: a play of `blocks/place` takes a minute against the fake."""


async def played(group_id: str, *, again: bool = False) -> Play:
    if group_id in _PLAYS and not again:
        return _PLAYS[group_id]
    _PLAYS[group_id] = await play(group_id)
    return _PLAYS[group_id]


async def play(group_id: str) -> Play:
    transcript = Transcript(group_id=group_id, server="fake")
    server = ControlServer(commands=COMMANDS)
    async with playing(server, transcript) as context:
        await GROUPS[group_id].run(context)
    return read(transcript)


def actions(window: Window) -> list[int]:
    return [int(str(fields["action"])) for name, fields in window.sent if name == PLAYER_ACTION]


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_each_group_has_the_drop_masks_and_no_prerequisite(group_id: str) -> None:
    group = GROUPS[group_id]

    # dig-survival is timed by the clock (a frozen world still ticks its players): see `_dig`.
    expected = GroupKind.EXACT if group_id == "blocks/dig-survival" else GroupKind.TICK_EXACT
    assert group.kind is expected
    assert group.requires == ()
    assert group.masks == blocks.DROP_MASKS


def test_only_dig_creative_asks_for_creative_mode() -> None:
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert GROUPS["blocks/dig-creative"].spec(default).game_mode is GameMode.CREATIVE
    assert GROUPS["blocks/dig-survival"].spec(default) == default
    assert GROUPS["blocks/place"].spec(default) == default
    assert GROUPS["blocks/dig-creative"].spec(default) == replace(
        default, game_mode=GameMode.CREATIVE
    )


def test_the_windows_compare_the_block_the_cracks_the_drops_and_the_slots() -> None:
    assert set(blocks_player.PACKETS) == {
        "minecraft:block_update",
        "minecraft:block_changed_ack",
        "minecraft:block_destruction",
        "minecraft:level_event",
        "minecraft:add_entity",
        "minecraft:set_entity_data",
        "minecraft:container_set_slot",
    }
    assert len(blocks_player.PACKETS) == len(set(blocks_player.PACKETS))


@pytest.mark.parametrize(
    ("speed", "hardness", "divisor", "ticks"),
    [
        (2.0, 1.5, 30, 23),  # a wooden pickaxe on stone: 0.0444 a tick, 22.5 rounded up
        (6.0, 1.5, 30, 8),  # an iron pickaxe on stone: 0.1333 a tick
        (1.0, 0.5, 30, 15),  # a hand on dirt: 0.0667 a tick, a binary32 sum that reaches 1 at 15
        (1.0, 1.5, 100, 151),  # a hand on stone: the binary32 sum is just short of 1 at 150
    ],
)
def test_break_ticks_counts_the_ticks_a_client_adds_its_progress(
    speed: float, hardness: float, divisor: int, ticks: int
) -> None:
    assert blocks_player.break_ticks(speed, hardness, divisor) == ticks


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_control_freezes_and_undoes_its_settings_after_the_last_window(group_id: str) -> None:
    result = await played(group_id)

    assert result.windows[0].before[-1] != "tick unfreeze"
    assert "tick freeze" in result.commands
    assert "gamerule random_tick_speed 0" in result.commands
    assert "gamerule random_tick_speed 3" in result.after
    assert result.commands[-1] == "tick unfreeze"


@pytest.mark.asyncio
async def test_the_survival_digger_starts_in_one_window_and_finishes_in_the_next() -> None:
    result = await played("blocks/dig-survival")
    cases = blocks_player.SURVIVAL_CASES

    assert len(result.windows) == 2 * len(cases)
    for starting, finishing, case in zip(
        result.windows[::2], result.windows[1::2], cases, strict=True
    ):
        assert actions(starting) == [START]
        assert actions(finishing) == [STOP]
        assert f"setblock 8 -60 6 {case.block}" in starting.before
        assert f"item replace entity digger hotbar.0 with {case.tool}" in starting.before
        assert finishing.before == ()  # nothing between the start and the finish but the wait
    assert {window.ticks for window in result.windows} == {0}  # the clock times it, not a step


def test_the_survival_digs_cover_the_tools_and_blocks_the_issue_names() -> None:
    cases = blocks_player.SURVIVAL_CASES

    assert {(case.block, case.tool) for case in cases} == {
        ("minecraft:stone", "minecraft:wooden_pickaxe"),
        ("minecraft:stone", "minecraft:iron_pickaxe"),
        ("minecraft:stone", "minecraft:air"),
        ("minecraft:dirt", "minecraft:air"),
        ("minecraft:obsidian", "minecraft:iron_pickaxe"),
    }
    assert cases[0].block == "minecraft:obsidian"  # refused only while the digger is new


@pytest.mark.asyncio
async def test_the_survival_digger_waits_for_its_uptime_before_the_first_dig(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept: list[float] = []
    real_sleep = asyncio.sleep

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(blocks_player, "UPTIME_S", 8.0)
    monkeypatch.setattr(blocks_player.asyncio, "sleep", sleep)
    await played("blocks/dig-survival", again=True)

    assert 8.0 in slept


@pytest.mark.asyncio
async def test_the_creative_digger_only_starts_and_never_finishes() -> None:
    result = await played("blocks/dig-creative")

    assert [actions(window) for window in result.windows] == [[START]] * len(result.windows)
    assert {window.ticks for window in result.windows} == {1}
    assert any("iron_sword" in " ".join(window.before) for window in result.windows)


@pytest.mark.asyncio
async def test_the_digger_places_once_in_each_window_with_the_face_and_cursor_of_its_case() -> None:
    result = await played("blocks/place")
    cases = blocks_player.PLACE_CASES

    assert len(result.windows) == len(cases)
    for window, case in zip(result.windows, cases, strict=True):
        [(name, fields)] = window.sent
        assert name == USE_ITEM_ON
        assert fields["face"] == int(case.face)
        assert (fields["cursor_x"], fields["cursor_y"], fields["cursor_z"]) == case.cursor
        assert fields["pos"] == dict(zip("xyz", case.on, strict=True))
        assert f"item replace entity digger hotbar.0 with {case.item} {case.count}" in window.before
        assert window.ticks == 1


def test_the_placements_cover_each_block_and_face_the_issue_names() -> None:
    cases = blocks_player.PLACE_CASES

    for item in ("oak_stairs", "oak_log"):
        assert {case.face for case in cases if case.item == f"minecraft:{item}"} >= set(Face)
    for item in ("oak_slab", "oak_door", "torch", "red_bed"):
        assert any(case.item == f"minecraft:{item}" for case in cases)
    assert any("short_grass" in " ".join(case.setup) for case in cases)
    assert any("snow" in " ".join(case.setup) for case in cases)
    assert any("armor_stand" in " ".join(case.setup) for case in cases)
    assert any("oak_slab[type=bottom]" in " ".join(case.setup) for case in cases)


@pytest.mark.asyncio
async def test_every_bot_is_moved_off_the_blocks_before_the_first_window() -> None:
    result = await played("blocks/place")

    moved = [c for c in result.commands if c.startswith("tp ")]
    assert {c.split()[1] for c in moved} == {"digger", "watcher", "control"}
    assert result.commands.index(moved[-1]) < result.commands.index("tick freeze")


@pytest.mark.asyncio
async def test_each_placement_empties_the_cells_from_the_top_down_and_kills_the_items() -> None:
    result = await played("blocks/place")

    before = result.windows[0].before
    fills = [c for c in before if c.startswith("fill ")]
    tops = [int(c.split()[2]) for c in fills]
    assert tops == sorted(tops, reverse=True)  # a torch or a door goes before its support
    assert before.index("kill @e[type=minecraft:item]") > before.index(fills[-1])
