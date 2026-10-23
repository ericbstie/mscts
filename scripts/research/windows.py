"""Research only: a play's Observation windows as text, each packet marked compared or not.

`windows_text` reads a Transcript. A window has no name in it, so a window is its number
and the packets its `observe:open` Mark narrows it to. Under the heading, one line for
each packet a Bot sent or received in the window, in time order:

    <ms since the window opened>  [tick <k>]  <Bot>  <status>  <packet name>  <decoded fields>

The status is `sent`, `compared` or `not compared`: whether the Comparison takes a received
packet (`compare.window_takes`). A Transcript of a tick-exact Group also gives each packet
the tick it came on, as the Comparison counts them.

Usage: windows.py GROUP [--full]

Boots one Instance of the vanilla Reference with the ServerSpec the Group asks for, plays
the registered Group GROUP once on it, stops it and prints `windows_text` of the
Transcript. `--full` prints every packet's fields, not the first 200 characters. A Group
that raised prints the windows it played before that, then what it raised, and exits 1.
Read it before a 20-play Self-check: a window whose compared packet nobody sent compares
nothing (#359).
"""

import argparse
import asyncio
import shutil
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from mscts import install
from mscts.adapters.vanilla import VanillaAdapter
from mscts.bot import status_probe
from mscts.cache import cache_dir
from mscts.codec.packets import Direction
from mscts.compare import (
    OBSERVE_CLOSE,
    OBSERVE_NO_PLAY,
    OBSERVE_OPEN,
    _Ticks,
    window_takes,
)
from mscts.group import GROUPS, Group
from mscts.run import GroupError, run_group
from mscts.runner import free_endpoint, running
from mscts.spec import ServerSpec
from mscts.target import TARGET
from mscts.transcript import Event, Mark, Transcript

FIELDS_WIDTH = 200
"""How many characters of a packet's decoded fields a line shows, by default."""
READY_TIMEOUT_S = 120.0  # a cold vanilla boot unpacks bundled libraries and makes a world
STOP_TIMEOUT_S = 30.0
_NS_PER_MS = 1_000_000
_SENT, _COMPARED, _NOT_COMPARED = "sent", "compared", "not compared"
_STATUS_WIDTH = len(_NOT_COMPARED)
_TICK_WIDTH = len("tick 999")


def windows_text(transcript: Transcript, *, width: int | None = FIELDS_WIDTH) -> str:
    """`transcript` as text: a heading, then each Observation window and the packets in it.

    A packet's fields are cut to `width` characters (None for all of them).
    """
    lines = [f"{transcript.group_id} on {transcript.server}"]
    opens = sorted(
        (mark for mark in transcript.marks if mark.label.split(" ")[0] == OBSERVE_OPEN),
        key=lambda mark: mark.t_ns,
    )
    if not opens:
        return "\n".join([*lines, "no Observation window"])
    layout = _Layout.of(transcript, width=width)
    for number, (opened, later) in enumerate(zip(opens, [*opens[1:], None], strict=True), 1):
        lines.append(_heading(number, opened))
        lines.extend(
            layout.line(
                event,
                status=_status(transcript, event),
                offset_ms=(event.t_ns - opened.t_ns) / _NS_PER_MS,
            )
            for event in _in_window(transcript, opened.t_ns, None if later is None else later.t_ns)
        )
    return "\n".join(lines)


def _heading(number: int, opened: Mark) -> str:
    """The line that opens a window: its number, and what its Mark narrows it to."""
    names = opened.label.split(" ")[1:]
    if names == [OBSERVE_NO_PLAY]:
        what = "compares no play packet"
    elif names:
        what = f"narrowed to {', '.join(names)}"
    else:
        what = "every packet"
    return f"window {number} ({what})"


def _in_window(transcript: Transcript, opened: int, next_opened: int | None) -> list[Event]:
    """The Events inside the window that opened at `opened`, each Bot's up to its own close.

    As the Comparison reads a window, a Bot's runs from the open Mark to its own close Mark
    (`observe:close <Bot>`), else to the one that names no Bot, else to where the next
    window opens (`next_opened`), or to the end. An Event stamped at a Mark's time is after it.
    """
    ends = {
        bot: _close_of(transcript, bot, opened=opened, next_opened=next_opened)
        for bot in {event.bot for event in transcript.events}
    }
    return [
        event
        for event in transcript.events
        if opened <= event.t_ns and ((end := ends[event.bot]) is None or event.t_ns < end)
    ]


def _close_of(
    transcript: Transcript, bot: str, *, opened: int, next_opened: int | None
) -> int | None:
    """When the window that opened at `opened` closes for `bot`; None if it never does."""
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


def _status(transcript: Transcript, event: Event) -> str:
    """`sent` for a packet the Bot sent; else whether the Comparison takes it."""
    if event.packet.direction is Direction.SERVERBOUND:
        return _SENT
    return _COMPARED if window_takes(transcript, event) else _NOT_COMPARED


@dataclass(frozen=True, slots=True)
class _Layout:
    """How a packet's line looks, for one Transcript.

    Attributes:
        ticks: For each Bot, its ticks (`compare._Ticks`), or None if it has none.
        bot_width: The length of the longest Bot name, which pads the others.
        width: How many characters of the fields a line shows; None for all.
    """

    ticks: dict[str, _Ticks | None]
    bot_width: int
    width: int | None

    @classmethod
    def of(cls, transcript: Transcript, *, width: int | None) -> Self:
        """The layout for the Bots of `transcript`."""
        bots = {event.bot for event in transcript.events}
        return cls(
            ticks={bot: _Ticks.of(transcript, bot) for bot in bots},
            bot_width=max(map(len, bots), default=0),
            width=width,
        )

    def line(self, event: Event, *, status: str, offset_ms: float) -> str:
        """One line for `event`, `offset_ms` after its window opened."""
        packet = event.packet
        return (
            f"{offset_ms:9.1f} ms  {self._tick(event)}{event.bot:<{self.bot_width}}  "
            f"{status:<{_STATUS_WIDTH}}  {packet.name}  {self._fields(event)}"
        )

    def _tick(self, event: Event) -> str:
        """The column that gives the tick `event` came on, if any Bot has ticks."""
        if not any(self.ticks.values()):
            return ""
        ticks = self.ticks[event.bot]
        text = "" if ticks is None else f"tick {ticks.of_arrival(event.t_ns):>3}"
        return f"{text:<{_TICK_WIDTH}}  "

    def _fields(self, event: Event) -> str:
        """`event`'s decoded fields, or its payload in hex if it has no schema; cut to width."""
        packet = event.packet
        text = (
            f"payload {packet.payload.hex()}"
            if packet.fields is None
            else repr(dict(packet.fields))
        )
        if self.width is None or len(text) <= self.width:
            return text
        return text[: self.width - 1] + "…"


async def play(group: Group, workdir: Path) -> Transcript:
    """Boot one vanilla Instance in `workdir`, play `group` once on it, and stop it.

    The Instance boots with the ServerSpec the Group asks for (`group.spec`), as a Run does.

    Raises:
        install.ProvisionError: There is no vanilla Installation to boot.
        GroupError: The Group raised; it holds the Transcript so far.
    """
    adapter = VanillaAdapter()
    installation = install.require(adapter, TARGET, cache_dir())
    endpoint = free_endpoint()
    spec = group.spec(ServerSpec(host=endpoint.host, port=endpoint.port))
    plan = adapter.prepare(installation, spec, workdir)
    async with running(
        plan,
        ready=status_probe(TARGET),
        ready_timeout=READY_TIMEOUT_S,
        stop_timeout=STOP_TIMEOUT_S,
    ) as instance:
        return await run_group(group, instance.endpoint, server=adapter.name)


def _play_in_new_workdir(group: Group) -> Transcript:
    """`play` of `group` in a new directory, which is removed afterwards."""
    workdir = Path(tempfile.mkdtemp(prefix="mscts-research-windows-"))
    try:
        return asyncio.run(play(group, workdir))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse `argv` (or sys.argv[1:]); SystemExit(2) on a bad argument."""
    parser = argparse.ArgumentParser(prog="windows.py", description=__doc__)
    parser.add_argument("group", help="the id of a registered Group, such as player/fire")
    parser.add_argument("--full", action="store_true", help="print every packet's fields, uncut")
    return parser.parse_args(argv)


def _fail(message: str) -> int:
    """Print `message` to stderr as windows.py's; the exit code that says it failed."""
    print(f"windows.py: {message}", file=sys.stderr)
    return 1


def main(argv: Sequence[str] | None = None, *, groups: Mapping[str, Group] = GROUPS) -> int:
    """Run windows.py: print the windows of the Group `argv` names; 1 if it could not."""
    args = parse_args(argv)
    if args.group not in groups:
        return _fail(f"no Group is registered as {args.group!r}")
    width = None if args.full else FIELDS_WIDTH
    try:
        played = _play_in_new_workdir(groups[args.group])
    except install.ProvisionError as error:
        return _fail(str(error))
    except GroupError as error:
        print(windows_text(error.transcript, width=width))
        return _fail(f"{args.group} failed: {error}")
    print(windows_text(played, width=width))
    return 0


if __name__ == "__main__":
    sys.exit(main())
