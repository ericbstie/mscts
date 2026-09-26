"""Transcripts: the ordered, timestamped record of what each Bot sent and received."""

import bisect
import time
from dataclasses import dataclass, field

from mscts.codec.packets import Packet


@dataclass(frozen=True, slots=True)
class Event:
    """One Packet a Bot sent or received.

    Attributes:
        t_ns: When it was sent or received, in nanoseconds since the Transcript started.
        bot: The name of the Bot.
        packet: The Packet. Its direction tells sent (serverbound) from received
            (clientbound).
    """

    t_ns: int
    bot: str
    packet: Packet


@dataclass(frozen=True, slots=True)
class Mark:
    """A named timestamp a Scenario records so a Measurement can be computed.

    Attributes:
        t_ns: When it was recorded, in nanoseconds since the Transcript started.
        label: The name, e.g. `status:start`.
    """

    t_ns: int
    label: str


@dataclass
class Transcript:
    """The ordered, timestamped record of every Packet each Bot sent and received, plus Marks.

    A plain data holder: it does no I/O. Every `t_ns` in it counts nanoseconds on the
    monotonic clock from `start_ns`.

    Attributes:
        scenario_id: The Scenario that produced it, e.g. `status/basic`.
        server: The name of the Adapter whose Instance it ran against.
        events: Every Packet sent and received.
        marks: Every Mark.
        start_ns: `time.monotonic_ns()` when the Transcript started. It only anchors
            this process's clock, so equality ignores it.
    """

    scenario_id: str
    server: str
    events: list[Event] = field(default_factory=list)
    marks: list[Mark] = field(default_factory=list)
    start_ns: int = field(default_factory=time.monotonic_ns, compare=False)

    def now_ns(self) -> int:
        """Return the monotonic nanoseconds since the Transcript started."""
        return time.monotonic_ns() - self.start_ns

    def record(self, bot: str, packet: Packet, *, t_ns: int) -> Event:
        """Add the Event that `bot` sent or received `packet` at `t_ns`, and return it.

        `events` stays ordered by `t_ns`, with equal times in recording order. A Bot
        can record out of time order: a received frame is stamped when it arrives but
        recorded when the Bot takes it, possibly after the Bot sent something.

        Raises:
            ValueError: `t_ns` is before the start or after `now_ns()`.
        """
        if t_ns < 0:
            msg = f"t_ns {t_ns} is before the Transcript started"
            raise ValueError(msg)
        if t_ns > self.now_ns():
            msg = f"t_ns {t_ns} is in the future"
            raise ValueError(msg)
        event = Event(t_ns=t_ns, bot=bot, packet=packet)
        bisect.insort_right(self.events, event, key=_event_time)
        return event


def _event_time(event: Event) -> int:
    return event.t_ns
