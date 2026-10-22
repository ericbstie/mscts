"""What Control sent in a played tick-exact Group, read from its Transcript window by window."""

from dataclasses import dataclass

import mscts.groups  # noqa: F401 - registers the shipped Groups `replay` plays
from mscts.codec.packets import Direction
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN, TICK_MARK
from mscts.group import GROUPS
from mscts.transcript import Transcript
from support.control import CHAT_COMMAND, CONTROL, MARKER, ControlServer, playing


@dataclass(frozen=True)
class Window:
    """One Observation window: its open Mark, Control's commands before it and in it, its ticks."""

    label: str
    before: tuple[str, ...]
    commands: tuple[str, ...]
    ticks: int


@dataclass(frozen=True)
class Play:
    """A played Group: its windows, and Control's commands before the first and after the last."""

    windows: tuple[Window, ...]
    first: tuple[str, ...]
    after: tuple[str, ...]


def control_commands(transcript: Transcript) -> list[tuple[int, str]]:
    """Control's commands with when, but its markers."""
    commands = [
        (event.t_ns, str((event.packet.fields or {})["command"]))
        for event in transcript.events
        if event.bot == CONTROL
        and event.packet.direction is Direction.SERVERBOUND
        and event.packet.name == CHAT_COMMAND
    ]
    return [(t_ns, command) for t_ns, command in commands if not command.startswith(MARKER)]


def read(transcript: Transcript) -> Play:
    """The windows of `transcript`, each from its open Mark to its last close Mark."""
    labels = [mark.label for mark in transcript.marks if mark.label.startswith(OBSERVE_OPEN)]
    opens = [mark.t_ns for mark in transcript.marks if mark.label.startswith(OBSERVE_OPEN)]
    closes = [mark.t_ns for mark in transcript.marks if mark.label == OBSERVE_CLOSE]
    assert len(opens) == len(closes), transcript.marks
    ticks = [
        m.t_ns for m in transcript.marks if m.label.startswith(TICK_MARK) and " " not in m.label
    ]
    control = control_commands(transcript)
    windows, previous = [], 0
    for label, opened, closed in zip(labels, opens, closes, strict=True):
        windows.append(
            Window(
                label=label,
                before=tuple(c for t, c in control if previous <= t < opened),
                commands=tuple(c for t, c in control if opened <= t <= closed),
                ticks=sum(opened <= t <= closed for t in ticks),
            )
        )
        previous = closed
    first = tuple(c for t, c in control if t < opens[0]) if opens else ()
    after = tuple(c for t, c in control if t > previous)
    return Play(tuple(windows), first, after)


async def replay(group_id: str, server: ControlServer) -> Play:
    """Play `group_id` against `server`; return what was read from its Transcript."""
    transcript = Transcript(group_id=group_id, server="fake")
    async with playing(server, transcript) as context:
        await GROUPS[group_id].run(context)
    return read(transcript)
