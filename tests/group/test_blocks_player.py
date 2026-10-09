"""The blocks Groups for a player: what the digger sends in each window, and what is undone after.

Every test plays a Group against a fake server and reads the Transcript for what the Bots sent
(the digger's actions, Control's commands) and the Marks (the Observation windows and the
ticks stepped). What a server answers is never asserted: the fake only answers the barrier and
Control's markers.
"""

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
START = 0
COMMANDS = tree("setblock", "fill", "tp", "tick", "gamerule", "kill", "item", "summon", "tellraw")
GROUP_IDS = ("blocks/dig-creative", "blocks/place")
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
    )


pytestmark = pytest.mark.timeout(300)
"""A play of `blocks/place` takes about 70 s against the fake, more under load."""


@pytest.fixture(autouse=True)
def long_play(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(test_control, "PLAY_TIMEOUT_S", 280.0)


_PLAYS: dict[str, Play] = {}
"""What each Group sent, kept: a play of `blocks/place` takes a minute against the fake."""


async def played(group_id: str) -> Play:
    if group_id in _PLAYS:
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

    assert group.kind is GroupKind.TICK_EXACT
    assert group.requires == ()
    assert group.masks == blocks.DROP_MASKS


def test_only_dig_creative_asks_for_creative_mode() -> None:
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert GROUPS["blocks/dig-creative"].spec(default).game_mode is GameMode.CREATIVE
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
async def test_the_creative_digger_only_starts_and_never_finishes() -> None:
    result = await played("blocks/dig-creative")

    assert [actions(window) for window in result.windows] == [[START]] * len(result.windows)
    assert {window.ticks for window in result.windows} == {1}
    assert all("tick step 1" in window.before for window in result.windows)
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
        assert "tick step 1" in window.before  # the blocks set reach the Bots first
        assert window.yaw == case.yaw


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
    assert "kill @e[tag=mscts_blocks_player]" in result.after
