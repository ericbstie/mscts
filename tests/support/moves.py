"""The moves and commands a played Group sent, read from its Transcript window by window."""

from dataclasses import dataclass

from mscts.codec.packets import Direction
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN
from mscts.transcript import Transcript
from support.control import CHAT_COMMAND, CONTROL, MARKER


def opened(*names: str) -> str:
    """The label of the Mark that opens a window comparing the packets `names`."""
    return f"{OBSERVE_OPEN} {' '.join(names)}"


MOVES = ("minecraft:move_player_pos", "minecraft:move_player_pos_rot")


@dataclass(frozen=True)
class Window:
    """One Observation window: its label, and what was sent inside it, in order.

    Attributes:
        label: Its open Mark's label.
        sent: Each Bot's moves, as `(bot, (x, y, z))`, and Control's commands, as
            `("control", command)`, in the order they were sent; markers left out.
        before: Control's commands since the last window closed.
    """

    label: str
    sent: tuple[tuple[str, object], ...]
    before: tuple[str, ...]

    def moves(self, bot: str) -> list[tuple[float, float, float]]:
        return [what for who, what in self.sent if who == bot]  # ty: ignore[invalid-return-type]


@dataclass(frozen=True)
class Play:
    """A played Group: each window, Control's commands before the first and after the last."""

    windows: tuple[Window, ...]
    first: tuple[str, ...]
    after: tuple[str, ...]


def moves_and_commands(transcript: Transcript) -> list[tuple[int, str, object]]:
    """Every move and every command but a marker, with when and by whom."""
    sent: list[tuple[int, str, object]] = []
    for event in transcript.events:
        if event.packet.direction is not Direction.SERVERBOUND:
            continue
        fields = event.packet.fields or {}
        if event.packet.name in MOVES:
            sent.append((event.t_ns, event.bot, (fields["x"], fields["y"], fields["z"])))
        elif event.packet.name == CHAT_COMMAND and not str(fields["command"]).startswith(MARKER):
            sent.append((event.t_ns, event.bot, str(fields["command"])))
    return sent


def read(transcript: Transcript) -> Play:
    """The windows of `transcript`, each from its open Mark to the end of every Bot's."""
    sent = moves_and_commands(transcript)
    opens = [mark.t_ns for mark in transcript.marks if mark.label.startswith(OBSERVE_OPEN)]
    labels = [mark.label for mark in transcript.marks if mark.label.startswith(OBSERVE_OPEN)]
    closes = [mark.t_ns for mark in transcript.marks if mark.label == OBSERVE_CLOSE]
    assert len(opens) == len(closes), transcript.marks
    windows = []
    previous = 0
    for label, opened, closed in zip(labels, opens, closes, strict=True):
        windows.append(
            Window(
                label=label,
                sent=tuple((who, what) for t, who, what in sent if opened <= t <= closed),
                before=tuple(
                    str(what) for t, who, what in sent if previous <= t < opened and who == CONTROL
                ),
            )
        )
        previous = closed
    control = [(t, str(what)) for t, who, what in sent if who == CONTROL]
    first = tuple(c for t, c in control if t < opens[0]) if opens else ()
    return Play(tuple(windows), first, tuple(c for t, c in control if t > previous))
