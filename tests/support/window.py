"""What one Bot recorded inside an Observation window, read by the window's Marks (#249).

A Bot records a packet when it takes it, and `Transcript.record` keeps the events in time
order, so a packet taken late lands among earlier ones. A window read by an index into
`transcript.events` can then take a packet from before it, or miss one inside it. The
window's Marks are times, and Compare reads a window by them; so does this.
"""

from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN
from mscts.transcript import Event, Transcript


def window_since(transcript: Transcript, bot: str, since_ns: int) -> list[Event]:
    """Every event of `bot` inside the first Observation window opened at or after `since_ns`.

    The events are in time order; none if no window opened since. As in Compare, the
    window starts at its `observe:open` Mark and ends at the Bot's own `observe:close <bot>`
    Mark, or at the `observe:close` that names no Bot if it has none; a window with no
    close Mark (its body raised) runs to where the next one opens, or to the end. An event
    stamped at a Mark's time is after the Mark.
    """
    opens = sorted(
        mark.t_ns
        for mark in transcript.marks
        if mark.label.split(" ", 1)[0] == OBSERVE_OPEN and mark.t_ns >= since_ns
    )
    if not opens:
        return []
    opened, *later = opens
    closed = _close_of(transcript, bot, opened=opened, next_opened=min(later, default=None))
    return [
        event
        for event in transcript.events
        if event.bot == bot and opened <= event.t_ns and (closed is None or event.t_ns < closed)
    ]


def _close_of(
    transcript: Transcript, bot: str, *, opened: int, next_opened: int | None
) -> int | None:
    """When the window opened at `opened` closes for `bot`; None if it never does.

    A window with no close Mark of its own ends where the next one opens, if one does.
    """
    for label in (f"{OBSERVE_CLOSE} {bot}", OBSERVE_CLOSE):  # its own close wins
        closes = [
            mark.t_ns
            for mark in transcript.marks
            if mark.label == label
            and opened <= mark.t_ns
            and (next_opened is None or mark.t_ns < next_opened)
        ]
        if closes:
            return min(closes)
    return next_opened
