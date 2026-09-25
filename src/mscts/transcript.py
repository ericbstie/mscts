"""Transcripts: the ordered, timestamped record of what each Bot sent and received."""

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
