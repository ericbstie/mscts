"""The world border Groups: what each Bot sends, in which window, and what is undone after.

Every test reads one play of a Group against a fake server: what Control and the Bots sent (the
commands and the moves), and the Marks (the Observation windows and the ticks stepped). What a
server answers is never asserted: the fake answers Control's markers, the barrier, and each
command with a line of chat (`BlocksServer`).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from unittest import mock

import pytest
from support import blocks_server, player_server
from support.blocks_server import BlocksServer
from support.control import CONTROL, SYSTEM_CHAT, playing, tree
from support.moves import MOVES, moves_and_commands
from support.player_server import Hurt, PlayerServer
from support.ticks import barriers_before_steps

from mscts.bot import HANDLED_REQUESTS
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN, TICK_MARK
from mscts.group import GROUPS, GroupKind
from mscts.groups import player
from mscts.net import ProtocolError
from mscts.spec import Difficulty, ServerSpec
from mscts.transcript import Transcript

WARDEN = "warden"
CHAT = "minecraft:system_chat"
COMMANDS = tree("worldborder", "gamerule", "gamemode", "tp", "tick", "kill", "tellraw")
BORDER = (
    "minecraft:initialize_border",
    "minecraft:set_border_size",
    "minecraft:set_border_lerp_size",
    "minecraft:set_border_center",
    "minecraft:set_border_warning_distance",
    "minecraft:set_border_warning_delay",
)
FEEDBACK_AFTER_S = 0.3
"""How late the fake gives the warden its feedback: a server behind schedule."""

SET_UP = (
    "gamerule player_movement_check false",
    "gamerule respawn_radius 0",
    "gamerule natural_health_regeneration false",
    "gamemode creative control",
)
"""What Control does before the Bots join, and then the freeze."""
UNDO_BORDER = (
    "worldborder set 59999968",
    "worldborder center 0.0 0.0",
    "worldborder warning distance 5",
    "worldborder warning time 300",
    "worldborder damage amount 0.2",
    "worldborder damage buffer 5",
)
UNDO_SETTINGS = (
    "gamemode survival control",
    "gamerule natural_health_regeneration true",
    "gamerule respawn_radius 10",
    "gamerule player_movement_check true",
)
UNDO = (*UNDO_BORDER, *UNDO_SETTINGS)
"""What Control undoes after the last window, in order: the border, then the rules. A Bot is put
back at the spawn before all of it. `tick unfreeze` comes last, when the Group ends."""


def opened(*names: str) -> str:
    """The label of the Mark that opens a window comparing the packets `names`."""
    return f"{OBSERVE_OPEN} {' '.join(names)}"


@dataclass(frozen=True)
class Window:
    """One Observation window: what was sent in it, and how often the warden heard chat.

    Attributes:
        label: Its open Mark's label.
        before: Control's commands since the last window closed.
        sent: Every command and move sent inside it, as `(bot, what)`, in order.
        heard: How many `system_chat` the warden received inside it.
        ticks: How many ticks were stepped inside it.
    """

    label: str
    before: tuple[str, ...]
    sent: tuple[tuple[str, object], ...]
    heard: int
    ticks: int

    def by(self, bot: str) -> list[object]:
        """What `bot` sent inside the window."""
        return [what for who, what in self.sent if who == bot]


@dataclass(frozen=True)
class Play:
    """A played Group: each window, Control's commands before the first and after the last."""

    windows: tuple[Window, ...]
    first: tuple[str, ...]
    after: tuple[str, ...]
    transcript: Transcript


def read(transcript: Transcript) -> Play:
    """The windows of `transcript`, each from its open Mark to its close Mark."""
    sent = moves_and_commands(transcript)
    marks = transcript.marks
    opens = [mark for mark in marks if mark.label.startswith(OBSERVE_OPEN)]
    closes = [mark for mark in marks if mark.label == OBSERVE_CLOSE]
    assert len(opens) == len(closes), marks
    ticks = [m.t_ns for m in marks if m.label.startswith(TICK_MARK) and " " not in m.label]
    heard = [
        event.t_ns
        for event in transcript.events
        if event.bot == WARDEN and event.packet.name == SYSTEM_CHAT
    ]
    control = [(t, str(what)) for t, who, what in sent if who == CONTROL]
    windows, previous = [], 0
    for start, end in zip(opens, closes, strict=True):
        inside = range(start.t_ns, end.t_ns + 1)
        windows.append(
            Window(
                label=start.label,
                before=tuple(c for t, c in control if previous <= t < start.t_ns),
                sent=tuple((who, what) for t, who, what in sent if t in inside),
                heard=sum(t in inside for t in heard),
                ticks=sum(t in inside for t in ticks),
            )
        )
        previous = end.t_ns
    first = tuple(c for t, c in control if t < opens[0].t_ns) if opens else ()
    after = tuple(c for t, c in control if t > closes[-1].t_ns)
    return Play(tuple(windows), first, after, transcript)


async def replay(group_id: str, server: BlocksServer) -> Play:
    """Play `group_id` against `server`; return what was read from its Transcript."""
    transcript = Transcript(group_id=group_id, server="fake")
    with mock.patch.object(blocks_server, "COMMANDS", COMMANDS):
        async with playing(server, transcript) as context:
            await GROUPS[group_id].run(context)
    return read(transcript)


_PLAYS: dict[str, Play] = {}
"""Each Group's play against a default fake server; no test changes it."""


async def play(group_id: str) -> Play:
    """The play of `group_id` against a default fake server, played the first time it is asked."""
    if group_id not in _PLAYS:
        _PLAYS[group_id] = await replay(group_id, BlocksServer())
    return _PLAYS[group_id]


def specs(group_id: str) -> Mapping[str, object]:
    """What a Group's spec changes in the default ServerSpec."""
    default = ServerSpec(host="127.0.0.1", port=25566)
    changed = GROUPS[group_id].spec(default)
    return {
        "difficulty": changed.difficulty,
        "operators": changed.operators,
    }


# `world/border-commands`

COMMANDS_ID = "world/border-commands"
RUN = (
    "worldborder set 20",
    "worldborder set 40 5",
    "worldborder center 10 10",
    "worldborder warning distance 3",
    "worldborder warning time 5",
    "worldborder damage amount 1",
    "worldborder damage buffer 2",
    "worldborder get",
)


def test_border_commands_is_exact_with_no_masks_and_the_warden_an_operator_on_normal() -> None:
    group = GROUPS[COMMANDS_ID]

    assert group.kind is GroupKind.EXACT
    assert group.requires == ()
    assert group.masks == ()
    assert specs(COMMANDS_ID) == {"difficulty": Difficulty.NORMAL, "operators": (WARDEN,)}


@pytest.mark.asyncio
async def test_border_commands_sets_the_world_up_and_freezes_it_before_the_first_window() -> None:
    result = await play(COMMANDS_ID)

    assert result.first == (*SET_UP, "tick freeze")


@pytest.mark.asyncio
async def test_border_commands_runs_each_command_as_the_warden_in_a_window_of_its_own() -> None:
    windows = (await play(COMMANDS_ID)).windows

    assert [window.by(WARDEN) for window in windows] == [[command] for command in RUN]
    assert {window.label for window in windows} == {opened("minecraft:system_chat", *BORDER)}


@pytest.mark.asyncio
async def test_border_commands_steps_no_tick_and_sends_nothing_but_the_warden_inside_a_window() -> (
    None
):
    windows = (await play(COMMANDS_ID)).windows

    assert [window.ticks for window in windows] == [0] * len(RUN)
    assert [window.by(CONTROL) for window in windows] == [[]] * len(RUN)


@pytest.mark.asyncio
async def test_the_warden_hears_its_own_feedback_inside_each_window_when_the_server_is_slow() -> (
    None
):
    # The feedback comes after the barrier's first answers, as on a server behind schedule: a
    # window that closed on the barrier would leave it outside.
    result = await replay(COMMANDS_ID, BlocksServer(feedback_after_s=FEEDBACK_AFTER_S))

    assert [window.heard for window in result.windows] == [1] * len(RUN)


@pytest.mark.asyncio
async def test_border_commands_puts_the_border_and_the_rules_back_and_unfreezes_last() -> None:
    result = await play(COMMANDS_ID)

    assert result.after == ("tp warden 0.5 -60 0.5", *UNDO, "tick unfreeze")


# `world/border-lerp`

LERP_ID = "world/border-lerp"
STEP = "tick step 1"
SPAWN = "0.5 -60 0.5"
GET = ["worldborder get"]


def test_border_lerp_is_tick_exact_with_no_masks_and_the_warden_an_operator_on_normal() -> None:
    group = GROUPS[LERP_ID]

    assert group.kind is GroupKind.TICK_EXACT
    assert group.requires == ()
    assert group.masks == ()
    assert specs(LERP_ID) == {"difficulty": Difficulty.NORMAL, "operators": (WARDEN,)}


@pytest.mark.asyncio
async def test_border_lerp_sets_a_border_of_20_once_the_world_is_frozen() -> None:
    result = await play(LERP_ID)

    assert result.first == (*SET_UP, "tick freeze", "worldborder set 20")


@pytest.mark.asyncio
async def test_border_lerp_starts_the_lerp_then_reads_the_size_after_each_of_12_steps() -> None:
    # Two steps past the end of the lerp: the border has stopped, and says nothing more.
    windows = (await play(LERP_ID)).windows

    assert windows[0].by(WARDEN) == ["worldborder set 40 10"]
    reads = [window for window in windows if window.by(WARDEN) == GET]
    assert [window.before for window in reads] == [(STEP,)] * 12 + [()]


@pytest.mark.asyncio
async def test_border_lerp_steps_outside_every_window_that_compares_chat() -> None:
    # An operator hears Control's `tick step` as admin chat.
    windows = (await play(LERP_ID)).windows

    chatty = [window for window in windows if window.label.startswith(opened(CHAT))]
    assert chatty
    assert [window.by(CONTROL) for window in chatty] == [[]] * len(chatty)
    assert [window.ticks for window in chatty] == [0] * len(chatty)


@pytest.mark.asyncio
async def test_border_lerp_has_a_second_bot_join_in_a_border_window_after_the_fourth_step() -> None:
    windows = (await play(LERP_ID)).windows

    joined = windows[5]
    assert joined.label == opened(*BORDER)
    assert joined.by(WARDEN) == []
    assert [window.by(WARDEN) for window in windows[1:5]] == [GET] * 4
    assert windows[6].before == (STEP,)


@pytest.mark.asyncio
async def test_border_lerp_steps_the_shrinking_lerp_in_one_window_of_the_border_packets() -> None:
    windows = (await play(LERP_ID)).windows

    shrunk, stepped, read = windows[-3:]
    assert shrunk.by(WARDEN) == ["worldborder set 10 10"]
    assert stepped.label == opened(*BORDER)
    assert stepped.by(CONTROL) == [STEP] * 12
    assert stepped.ticks == 12
    assert read.by(WARDEN) == GET
    assert len(windows) == 17


@pytest.mark.asyncio
async def test_border_lerp_puts_the_bots_and_the_border_back_and_unfreezes_last() -> None:
    result = await play(LERP_ID)

    assert result.after == (
        f"tp latecomer {SPAWN}",
        f"tp warden {SPAWN}",
        *UNDO,
        "tick unfreeze",
    )


# `world/border-collision`

COLLISION_ID = "world/border-collision"
WALKER = "walker"
COLLISION_PACKETS = ("minecraft:player_position", "minecraft:disconnect", *BORDER)
Y, Z = -60.0, 0.5
WALKS = (
    (6.5, [6.7, 6.9, 7.1, 7.3, 7.5, 7.7, 7.9, 8.1, 8.3, 8.5, 8.7, 8.9, 9.1]),
    (6.5, [6.8, 7.1, 7.4, 7.7, 8.0, 8.3, 8.6, 8.9, 9.2]),
    (6.5, [7.0, 7.5, 8.0, 8.5, 9.0]),
    (7.5, [8.5]),
    (9.5, [9.3, 9.1, 8.9, 8.7, 8.5, 8.3, 8.1, 7.9]),
)
"""Where each window puts the Bot, and the x it moves to, a move a tick: 0.2, 0.3 and 0.5 a tick
from 6.5, a jump of a block from 7.5, and 0.2 a tick from outside, back in."""


def test_border_collision_is_tick_exact_with_no_masks_on_normal_with_no_operator() -> None:
    group = GROUPS[COLLISION_ID]

    assert group.kind is GroupKind.TICK_EXACT
    assert group.requires == ()
    assert group.masks == ()
    assert specs(COLLISION_ID) == {"difficulty": Difficulty.NORMAL, "operators": ()}


@pytest.mark.asyncio
async def test_border_collision_turns_the_movement_check_back_on_and_sets_a_border_of_16() -> None:
    # The joins ran with the check off (a join can repeat its first position); the walk needs it.
    result = await play(COLLISION_ID)

    assert result.first == (
        *SET_UP,
        "gamerule player_movement_check true",
        "tick freeze",
        "worldborder set 16",
        f"tp {WALKER} 6.5 {Y} {Z}",
    )


@pytest.mark.asyncio
async def test_border_collision_walks_a_move_a_tick_in_a_window_of_its_own_for_each_walk() -> None:
    windows = (await play(COLLISION_ID)).windows

    assert [window.label for window in windows] == [opened(*COLLISION_PACKETS)] * len(WALKS)
    assert [window.ticks for window in windows] == [len(xs) for _, xs in WALKS]
    assert [window.before[-1:] for window in windows] == [
        (f"tp {WALKER} {start} {Y} {Z}",) for start, _ in WALKS
    ]


@pytest.mark.asyncio
async def test_border_collision_sends_each_move_before_the_step_that_should_see_it() -> None:
    windows = (await play(COLLISION_ID)).windows

    for window, (_, xs) in zip(windows, WALKS, strict=True):
        assert [what for _, what in window.sent] == [item for x in xs for item in ((x, Y, Z), STEP)]
        assert {who for who, _ in window.sent} == {WALKER, CONTROL}


@pytest.mark.asyncio
async def test_border_collision_waits_until_the_server_has_handled_a_move_before_it_steps() -> None:
    # The Bot and Control are on two connections: without the Bot's proof that the server has the
    # move, the step could reach the server first and the move land a tick late.
    transcript = (await play(COLLISION_ID)).transcript

    barriers = barriers_before_steps(transcript, WALKER, set(MOVES))

    assert len(barriers) == sum(len(xs) for _, xs in WALKS)
    assert set(barriers) == {HANDLED_REQUESTS}


@pytest.mark.asyncio
async def test_border_collision_puts_the_bot_and_the_border_back_and_unfreezes_last() -> None:
    result = await play(COLLISION_ID)

    assert result.after == (f"tp {WALKER} {SPAWN}", *UNDO, "tick unfreeze")


# `world/border-damage`

DAMAGE_ID = "world/border-damage"
VICTIM = "victim"
HIT_PACKETS = (
    "minecraft:damage_event",
    "minecraft:hurt_animation",
    "minecraft:entity_event",
    "minecraft:set_health",
    "minecraft:sound",
)
OUTSIDE = f"tp {VICTIM} 12.5 {Y} {Z}"
"""Where the Bot is put: 4.5 blocks past the border of 16, 2.5 past the buffer of 2."""
HURTS = {OUTSIDE: Hurt(10)}
"""The fake hurts the Bot every 10 ticks after the `tp`, as vanilla does (the immunity)."""
PLAYER_COMMANDS = tree(
    "worldborder", "gamerule", "gamemode", "tp", "tick", "kill", "tellraw", "effect"
)


def always_on_time() -> float:
    """A clock that never moves: no hit is ever older than its period allows."""
    return 0.0


async def hit_play(clock: Callable[[], float] = always_on_time) -> Play:
    """Play `world/border-damage` against a fake that hurts the Bot when it is put outside."""
    transcript = Transcript(group_id=DAMAGE_ID, server="fake")
    with (
        mock.patch.object(player_server, "COMMANDS", PLAYER_COMMANDS),
        mock.patch.object(player, "clock", clock),
    ):
        async with playing(PlayerServer(hurts=HURTS), transcript) as context:
            await GROUPS[DAMAGE_ID].run(context)
    return read(transcript)


def test_border_damage_is_exact_with_no_masks_on_normal_with_no_operator() -> None:
    group = GROUPS[DAMAGE_ID]

    assert group.kind is GroupKind.EXACT
    assert group.requires == ()
    assert group.masks == ()
    assert specs(DAMAGE_ID) == {"difficulty": Difficulty.NORMAL, "operators": ()}


@pytest.mark.asyncio
async def test_border_damage_sets_the_border_and_its_damage_then_makes_the_victim_fresh() -> None:
    result = await hit_play()

    assert result.first == (
        *SET_UP,
        "tick freeze",
        "worldborder set 16",
        "worldborder damage amount 1",
        "worldborder damage buffer 2",
        f"kill {VICTIM}",
    )


@pytest.mark.asyncio
async def test_border_damage_puts_the_bot_outside_inside_the_first_of_three_hit_windows() -> None:
    windows = (await hit_play()).windows

    assert [window.label for window in windows] == [
        opened(*HIT_PACKETS, "minecraft:player_position"),
        opened(*HIT_PACKETS),
        opened(*HIT_PACKETS),
    ]
    assert [window.by(CONTROL) for window in windows] == [[OUTSIDE], [], []]
    assert [window.ticks for window in windows] == [0, 0, 0]


def gap_clock(gap_s: float) -> Callable[[], float]:
    """A clock that reads each hit `gap_s` seconds after the one before, as the Group reads it."""
    readings = iter([0.0, gap_s, gap_s, 2 * gap_s, 2 * gap_s])
    return lambda: next(readings)


@pytest.mark.asyncio
async def test_border_damage_plays_on_when_a_window_opens_within_the_period_of_a_hit() -> None:
    # Hits are 10 ticks apart; a window may open up to 8 of them (0.4 s) after the last.
    result = await hit_play(gap_clock(0.38))

    assert len(result.windows) == 3


@pytest.mark.asyncio
async def test_border_damage_fails_when_a_window_opens_after_the_next_hit_may_have_come() -> None:
    with pytest.raises(ProtocolError, match="the next may have come between the windows"):
        await hit_play(gap_clock(0.45))


@pytest.mark.asyncio
async def test_border_damage_puts_the_bot_back_at_the_spawn_before_it_undoes_the_border() -> None:
    result = await hit_play()

    assert result.after == (f"tp {VICTIM} {SPAWN}", f"tp {VICTIM} {SPAWN}", *UNDO, "tick unfreeze")
