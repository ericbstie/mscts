"""The world border Groups: what each Bot sends, in which window, and what is undone after.

Every test reads one play of a Group against a fake server: what Control and the Bots sent (the
commands and the moves), and the Marks (the Observation windows and the ticks stepped). What a
server answers is never asserted: the fake answers Control's markers, the barrier, and each
command with a line of chat (`BlocksServer`).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from unittest import mock

import pytest
from support import blocks_server
from support.blocks_server import BlocksServer
from support.control import CONTROL, SYSTEM_CHAT, playing, tree
from support.moves import moves_and_commands

from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN, TICK_MARK
from mscts.group import GROUPS, GroupKind
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
    return Play(tuple(windows), first, tuple(c for t, c in control if t > closes[-1].t_ns))


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
