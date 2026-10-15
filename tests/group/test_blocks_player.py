"""The blocks Groups for a player: what the digger sends in each window, and what is undone after.

Every test plays a Group against a fake server and reads the Transcript for what the Bots sent
(the digger's actions, Control's commands) and the Marks (the Observation windows and the
ticks stepped). What a server answers is never asserted: the fake only answers the barrier and
Control's markers.
"""

import asyncio
from dataclasses import dataclass, replace

import pytest

from mscts.bot import HANDLED_REQUESTS, Face
from mscts.codec.packets import Direction
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN, TICK_MARK
from mscts.group import GROUPS, GroupKind
from mscts.groups import blocks, blocks_player
from mscts.spec import GameMode, ServerSpec
from mscts.transcript import Transcript
from tests.group import test_control
from tests.group.test_control import CHAT_COMMAND, MARKER, ControlServer, playing, tree
from tests.group.test_ticks import barriers_before_steps

PLAYER_ACTION, USE_ITEM_ON = "minecraft:player_action", "minecraft:use_item_on"
MOVE_ROT = "minecraft:move_player_rot"
START, STOP = 0, 3
COMMANDS = tree("setblock", "fill", "tp", "tick", "gamerule", "kill", "item", "summon", "tellraw")
PLACE_IDS = ("blocks/place", "blocks/place-attached")
SURVIVAL = "blocks/dig-survival"
STEPPED_IDS = ("blocks/dig-creative", *PLACE_IDS)
"""The Groups that step the world after each dig or placement."""
GROUP_IDS = (*STEPPED_IDS, SURVIVAL)
PLACE_CASES = {
    "blocks/place": blocks_player.PLACE_CASES,
    "blocks/place-attached": blocks_player.ATTACHED_CASES,
}
UNDO = ("gamerule random_tick_speed 3",)
"""What Control pushes first among its undos, so it runs last of the ones these tests read."""


@dataclass(frozen=True)
class Window:
    """One Observation window: what Control set before it, what the digger sent, ticks stepped."""

    before: tuple[str, ...]
    sent: tuple[tuple[str, dict[str, object]], ...]
    ticks: int
    yaw: float | None = None
    """The yaw the digger last sent before the window opened."""


@dataclass(frozen=True)
class Play:
    """A played Group: its windows, and Control's commands after the last one."""

    windows: tuple[Window, ...]
    after: tuple[str, ...]
    commands: tuple[str, ...]
    barriers: tuple[int, ...]
    """For each dig or placement a step follows: the digger's barrier requests in between."""
    slept: tuple[float, ...] = ()
    """What `blocks/dig-survival` waited, in seconds, in order."""


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
    turns = [
        (event.t_ns, float(str((event.packet.fields or {})["yaw"])))
        for event in transcript.events
        if event.bot == blocks_player.DIGGER
        and event.packet.direction is Direction.SERVERBOUND
        and "yaw" in (event.packet.fields or {})
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
                yaw=next((yaw for t, yaw in reversed(turns) if t < opened), None),
            )
        )
        previous = closed
    return Play(
        tuple(windows),
        tuple(c for t, c in control if t > previous),
        tuple(c for _, c in control),
        tuple(
            barriers_before_steps(transcript, blocks_player.DIGGER, {PLAYER_ACTION, USE_ITEM_ON})
        ),
    )


pytestmark = pytest.mark.timeout(300)
"""A play of a place Group takes about 40 s against the fake, more under load."""


@pytest.fixture(autouse=True)
def long_play(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(test_control, "PLAY_TIMEOUT_S", 280.0)


_PLAYS: dict[str, Play] = {}
"""What each Group sent, kept: a play of a place Group takes a minute against the fake."""


async def played(group_id: str) -> Play:
    if group_id in _PLAYS:
        return _PLAYS[group_id]
    _PLAYS[group_id] = await play(group_id)
    return _PLAYS[group_id]


async def play(group_id: str) -> Play:
    """Play `group_id` against the fake; `blocks/dig-survival` with a sleep that only records."""
    transcript = Transcript(group_id=group_id, server="fake")
    server = ControlServer(commands=COMMANDS)
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        await asyncio.sleep(0)

    async with playing(server, transcript) as context:
        if group_id == SURVIVAL:
            await blocks_player.survival(context, sleep)
        else:
            await GROUPS[group_id].run(context)
    return replace(read(transcript), slept=tuple(slept))


def actions(window: Window) -> list[int]:
    return [int(str(fields["action"])) for name, fields in window.sent if name == PLAYER_ACTION]


@pytest.mark.parametrize("group_id", GROUP_IDS)
def test_each_group_has_the_drop_masks_and_no_prerequisite(group_id: str) -> None:
    group = GROUPS[group_id]

    # A player's dig ticks run on the clock in a frozen world, so dig-survival cannot step them.
    assert group.kind is (GroupKind.EXACT if group_id == SURVIVAL else GroupKind.TICK_EXACT)
    assert group.requires == ()
    assert group.masks == blocks.DROP_MASKS


def test_only_dig_creative_asks_for_creative_mode() -> None:
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert GROUPS["blocks/dig-creative"].spec(default).game_mode is GameMode.CREATIVE
    assert all(GROUPS[group_id].spec(default) == default for group_id in (*PLACE_IDS, SURVIVAL))
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
@pytest.mark.parametrize("group_id", STEPPED_IDS)
async def test_the_dig_or_placement_reaches_the_server_before_the_step(group_id: str) -> None:
    result = await played(group_id)

    assert len(result.barriers) == len(result.windows)
    assert set(result.barriers) == {HANDLED_REQUESTS}


@pytest.mark.asyncio
async def test_the_creative_digger_only_starts_and_never_finishes() -> None:
    result = await played("blocks/dig-creative")

    assert [actions(window) for window in result.windows] == [[START]] * len(result.windows)
    assert {window.ticks for window in result.windows} == {1}
    assert all("tick step 1" in window.before for window in result.windows)
    assert any("iron_sword" in " ".join(window.before) for window in result.windows)


MINING = {
    ("minecraft:stone", "minecraft:air"): (1.0, 1.5, 100),
    ("minecraft:stone", "minecraft:wooden_pickaxe"): (2.0, 1.5, 30),
    ("minecraft:stone", "minecraft:iron_pickaxe"): (6.0, 1.5, 30),
    ("minecraft:dirt", "minecraft:air"): (1.0, 0.5, 30),
    ("minecraft:obsidian", "minecraft:diamond_pickaxe"): (8.0, 50.0, 30),
}
"""A tool's speed on a block, the block's hardness, and the divisor: 30 with the tool the block
needs (or when it needs none), 100 without (`BlockState.getDestroyProgress`)."""


def test_the_survival_windows_leave_out_the_packets_the_server_sends_on_its_clock() -> None:
    assert set(blocks_player.SURVIVAL_PACKETS) == set(blocks_player.PACKETS) - {
        "minecraft:block_destruction",
        "minecraft:level_event",
    }


def test_a_survival_dig_waits_50_ms_a_tick() -> None:
    assert blocks_player.TICK_S == 0.05  # 20 ticks a second


@pytest.mark.parametrize(
    ("speed", "hardness", "divisor", "ticks"),
    [
        (2.0, 1.5, 30, 15),  # a wooden pickaxe on stone: 0.0444 a tick, 0.7 at the 16th tick
        (6.0, 1.5, 30, 5),  # an iron pickaxe on stone
        (1.0, 0.5, 30, 10),  # a hand on dirt
        (1.0, 1.5, 100, 104),  # a hand on stone
        (8.0, 50.0, 30, 131),  # a diamond pickaxe on obsidian
        # Pins of the binary32 arithmetic: in binary64 the first would be 174, the second 140.
        (6.0, 50.0, 30, 175),  # the progress a tick is rounded to binary32
        (1.0, 2.0, 100, 139),  # the progress times the ticks is rounded to binary32
    ],
)
def test_accept_ticks_counts_the_ticks_of_dig_the_server_needs_before_it_accepts_a_finish(
    speed: float, hardness: float, divisor: int, ticks: int
) -> None:
    assert blocks_player.accept_ticks(speed, hardness, divisor) == ticks


@pytest.mark.parametrize(
    ("speed", "hardness", "divisor", "ticks"),
    [
        (1.0, 1.5, 100, 149),  # a hand on stone: 1/150 a tick, 1 in binary32 at 150
        (8.0, 50.0, 30, 187),  # a diamond pickaxe on obsidian: 0.00533 a tick
    ],
)
def test_delayed_ticks_counts_how_long_a_player_lives_before_an_early_finish_breaks_the_block(
    speed: float, hardness: float, divisor: int, ticks: int
) -> None:
    assert blocks_player.delayed_ticks(speed, hardness, divisor) == ticks


def test_the_early_finishes_use_the_tool_each_block_needs_and_finish_as_soon_as_they_start() -> (
    None
):
    assert [(case.dig.block, case.dig.tool) for case in blocks_player.EARLY_CASES] == [
        ("minecraft:stone", "minecraft:air"),
        ("minecraft:obsidian", "minecraft:diamond_pickaxe"),
    ]
    for case in blocks_player.EARLY_CASES:
        assert case.ticks == 1
        assert blocks_player.accept_ticks(*MINING[case.dig.block, case.dig.tool]) > 100


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


@pytest.mark.parametrize("mining", MINING.values())
def test_an_on_time_finish_waits_the_clients_time_and_has_slack_past_the_servers(
    mining: tuple[float, float, int],
) -> None:
    waits = blocks_player.finish_ticks(*mining)

    assert waits >= blocks_player.break_ticks(*mining)
    assert waits >= blocks_player.accept_ticks(*mining) + blocks_player.SLACK_TICKS
    assert waits in {blocks_player.break_ticks(*mining), blocks_player.accept_ticks(*mining) + 20}


def test_the_on_time_finishes_cover_the_issue_and_each_has_a_second_past_the_servers() -> None:
    assert [(case.dig.block, case.dig.tool) for case in blocks_player.SURVIVAL_CASES] == [
        ("minecraft:stone", "minecraft:wooden_pickaxe"),
        ("minecraft:stone", "minecraft:iron_pickaxe"),
        ("minecraft:dirt", "minecraft:air"),
        ("minecraft:stone", "minecraft:air"),
        ("minecraft:obsidian", "minecraft:diamond_pickaxe"),
    ]
    for case in blocks_player.SURVIVAL_CASES:
        least = blocks_player.accept_ticks(*MINING[case.dig.block, case.dig.tool])
        assert case.ticks - least >= 20


def test_the_aged_early_finishes_come_once_the_on_time_waits_have_aged_the_digger() -> None:
    assert [(case.dig.block, case.dig.tool, case.ticks) for case in blocks_player.AGED_CASES] == [
        ("minecraft:stone", "minecraft:air", 1),
        ("minecraft:obsidian", "minecraft:diamond_pickaxe", 1),
    ]
    waited = sum(case.ticks for case in blocks_player.SURVIVAL_CASES)
    for case in blocks_player.AGED_CASES:
        # The digger has lived through every on-time wait: a second past the delayed destroy's.
        assert waited >= blocks_player.delayed_ticks(*MINING[case.dig.block, case.dig.tool]) + 20


def test_the_survival_digs_are_played_early_then_on_time_then_early_from_an_aged_digger() -> None:
    assert (
        *blocks_player.EARLY_CASES,
        *blocks_player.SURVIVAL_CASES,
        *blocks_player.AGED_CASES,
    ) == blocks_player.FINISHES


def test_the_early_finishes_come_first_while_the_digger_is_new() -> None:
    # Each is refused for good only from a player alive under `delayed_ticks` (7.5 s for stone
    # by hand): the digger has just joined.
    early = len(blocks_player.EARLY_CASES)
    assert blocks_player.FINISHES[:early] == blocks_player.EARLY_CASES


@pytest.mark.asyncio
async def test_the_survival_digger_starts_in_one_window_and_finishes_in_the_next() -> None:
    result = await played(SURVIVAL)
    cases = blocks_player.FINISHES

    assert len(result.windows) == 2 * len(cases)
    for starting, finishing, case in zip(
        result.windows[::2], result.windows[1::2], cases, strict=True
    ):
        assert actions(starting) == [START]
        assert actions(finishing) == [STOP]
        assert f"setblock 8 -60 6 {case.dig.block}" in starting.before
        assert f"item replace entity digger hotbar.0 with {case.dig.tool}" in starting.before
        assert finishing.before == ()  # nothing between the start and the finish but the wait
    assert {window.ticks for window in result.windows} == {0}  # the clock times it, not a step
    assert result.slept == tuple(case.ticks * blocks_player.TICK_S for case in cases)


@pytest.mark.asyncio
async def test_each_survival_dig_ends_with_air_no_items_and_a_tick() -> None:
    result = await played(SURVIVAL)

    # Air disarms the destroy a refused finish leaves, on the digger's next tick.
    for before in (*(window.before for window in result.windows[2::2]), result.after):
        taking_away = before[: before.index("tick step 1") + 1]
        assert taking_away[-3:] == (
            "setblock 8 -60 6 minecraft:air",
            "kill @e[type=minecraft:item]",
            "tick step 1",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", PLACE_IDS)
async def test_the_digger_places_once_in_each_window_with_the_face_and_cursor_of_its_case(
    group_id: str,
) -> None:
    result = await played(group_id)
    cases = PLACE_CASES[group_id]

    assert len(result.windows) == len(cases)
    for window, case in zip(result.windows, cases, strict=True):
        [(name, fields)] = window.sent
        assert name == USE_ITEM_ON
        assert fields["face"] == int(case.face)
        assert (fields["cursor_x"], fields["cursor_y"], fields["cursor_z"]) == case.cursor
        assert fields["pos"] == dict(zip("xyz", case.on, strict=True))
        assert f"item replace entity digger hotbar.0 with {case.item} {case.count}" in window.before
        assert window.ticks == 1
        assert window.yaw == case.yaw


def test_the_placements_cover_each_block_and_face_the_issue_names() -> None:
    cases = (*blocks_player.PLACE_CASES, *blocks_player.ATTACHED_CASES)

    for item in ("oak_stairs", "oak_log"):
        assert {case.face for case in cases if case.item == f"minecraft:{item}"} >= set(Face)
    for item in ("oak_slab", "oak_door", "torch", "red_bed"):
        assert any(case.item == f"minecraft:{item}" for case in cases)
    assert any("short_grass" in " ".join(case.setup) for case in cases)
    assert any("snow" in " ".join(case.setup) for case in cases)
    assert any("armor_stand" in " ".join(case.setup) for case in cases)
    assert any("oak_slab[type=bottom]" in " ".join(case.setup) for case in cases)


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", GROUP_IDS)
async def test_every_bot_is_moved_off_the_blocks_before_the_first_window(group_id: str) -> None:
    result = await played(group_id)

    moved = [c for c in result.commands if c.startswith("tp ")]
    assert {c.split()[1] for c in moved} == {"digger", "watcher", "control"}
    assert result.commands.index(moved[-1]) < result.commands.index("tick freeze")


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", PLACE_IDS)
async def test_each_placement_empties_the_cells_from_the_top_down_and_kills_the_items(
    group_id: str,
) -> None:
    result = await played(group_id)

    before = result.windows[0].before
    fills = [c for c in before if c.startswith("fill ")]
    tops = [int(c.split()[2]) for c in fills]
    assert tops == sorted(tops, reverse=True)  # a torch or a door goes before its support
    assert before.index("kill @e[type=minecraft:item]") > before.index(fills[-1])
    assert "kill @e[tag=mscts_blocks_player]" in result.after
