"""What one Bot recorded inside an Observation window, read by the window's Marks (#249).

A Bot records a packet when it takes it, and `Transcript.record` keeps the events in time
order, so a packet taken late lands among earlier ones. A window read by an index into
`transcript.events` can then take a packet from before it, or miss one inside it. The
window's Marks are times, and Compare reads a window by them; so does this.
"""

from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN
from mscts.transcript import Event, Transcript


def last_window(transcript: Transcript, bot: str) -> list[Event]:
    """Every event of `bot` inside the last Observation window of `transcript`, in time order.

    As in Compare, the window starts at its `observe:open` Mark and ends at the Bot's own
    `observe:close <bot>` Mark, or at the `observe:close` that names no Bot if it has none;
    a window with no close Mark (its body raised) runs to the end. An event stamped at a
    Mark's time is after the Mark. Empty if the Transcript has no window.
    """
    opens = [mark.t_ns for mark in transcript.marks if _label(mark.label) == OBSERVE_OPEN]
    if not opens:
        return []
    opened = max(opens)
    closed = _close_of(transcript, bot, opened=opened)
    return [
        event
        for event in transcript.events
        if event.bot == bot and opened <= event.t_ns and (closed is None or event.t_ns < closed)
    ]


def _close_of(transcript: Transcript, bot: str, *, opened: int) -> int | None:
    """When the window opened at `opened` closes for `bot`; None if it never does."""
    for label in (f"{OBSERVE_CLOSE} {bot}", OBSERVE_CLOSE):  # its own close wins
        closes = [m.t_ns for m in transcript.marks if m.label == label and m.t_ns >= opened]
        if closes:
            return min(closes)
    return None


def _label(label: str) -> str:
    """A Mark's label without the names that follow it."""
    return label.split(" ", 1)[0]
