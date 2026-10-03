"""Timelines: a play's Transcript as text, to diagnose a play that did not match (#162)."""

from mscts.codec.packets import Direction
from mscts.compare import window_takes
from mscts.transcript import Event, Transcript

_ANSWER = "minecraft:award_stats"
"""The barrier's answer (`Bot.sync`): its line says how long after its Bot's last one it came."""
_NS_PER_MS = 1_000_000


def timeline(transcript: Transcript) -> str:
    """`transcript` as text: a heading, then each Event and Mark in time order, one per line.

    A line gives the time in milliseconds since the Transcript started, the Bot, and what
    happened: a Packet sent or received, or a Mark's label. A Mark comes before an Event
    of the same time, as a window takes an Event stamped at its open Mark. A received
    Packet says whether an Observation window takes it, if the Transcript has windows.
    An `award_stats` also says how long after its Bot's last one it arrived.
    """
    width = max((len(event.bot) for event in transcript.events), default=0)
    lines = [(mark.t_ns, 0, "", f"mark {mark.label}") for mark in transcript.marks]
    lines.extend(
        (event.t_ns, 1, event.bot, what)
        for event, what in zip(transcript.events, _what_happened(transcript), strict=True)
    )
    return "\n".join(
        [
            f"{transcript.group_id} on {transcript.server}",
            *(
                f"{t_ns / _NS_PER_MS:12.3f} ms  {bot:<{width}}  {what}"
                for t_ns, _, bot, what in sorted(lines, key=lambda line: line[:2])
            ),
        ]
    )


def _what_happened(transcript: Transcript) -> list[str]:
    """What each Event of `transcript` was, in order: sent, or received and where."""
    last_answer: dict[str, int] = {}
    result: list[str] = []
    for event in transcript.events:
        if event.packet.direction is Direction.SERVERBOUND:
            result.append(f"sent {event.packet.name}")
        else:
            where = _window(transcript, event)
            gap = _gap_to_last_answer(event, last_answer)
            result.append(f"received {event.packet.name}{where}{gap}")
    return result


def _gap_to_last_answer(event: Event, last_answer: dict[str, int]) -> str:
    """For an `award_stats`, how long after its Bot's last one it arrived, for its line.

    `last_answer` holds when each Bot's last `award_stats` arrived; an `award_stats`
    becomes its Bot's last there. Any other Packet, or a Bot's first answer, gets nothing.
    """
    if event.packet.name != _ANSWER:
        return ""
    last = last_answer.get(event.bot)
    last_answer[event.bot] = event.t_ns
    if last is None:
        return ""
    return f", {(event.t_ns - last) / _NS_PER_MS:.3f} ms after {event.bot}'s last"


def _window(transcript: Transcript, event: Event) -> str:
    """Where `event` fell, for its line: inside or outside the window, or nothing."""
    taken = window_takes(transcript, event)
    if taken is None:
        return ""
    return ", inside the window" if taken else ", outside the window"
