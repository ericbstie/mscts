"""Waiting until no player is online on an Instance, as its status says (#97).

`Bot.close()` only closes the socket, and a server removes the player later (vanilla on
its next tick). So whatever plays against an Instance after Bots have left it, a Run before
its next Group or a Group after one of its own Bots left, waits first, with
`until_no_player_online`. It asks the status (the request `status/basic` sends), so it works
the same on every Candidate (ADR-0001). What vanilla's status does when a player leaves, and
how long it takes, is in docs/research/2026-10-02-settle.md.
"""

import asyncio
import dataclasses
from collections.abc import Sequence

from mscts.bot import Bot
from mscts.codec.packets import CodecError
from mscts.net import Endpoint, ProtocolError
from mscts.target import TARGET
from mscts.transcript import Transcript

SETTLE_INTERVAL_S = 0.02
"""How long to wait between polls of an Instance's status while players are online.

Vanilla removes a closed Bot's player on its next tick (50 ms), and drops the cached
status in the same call (`ServerGamePacketListenerImpl.removePlayerFromWorld` calls
`MinecraftServer.invalidateStatus`, which the same tick's rebuild follows), so a poll
every 20 ms, under a tick, finds the Instance empty soon after it is
(docs/research/2026-10-02-settle.md).
"""

SETTLE_TIMEOUT_S = 2.0
"""How long to wait for an Instance to have no player online.

Measured live on vanilla 26.3: from the end of a Group to the first status that read
`players.online == 0` took 10 to 197 ms, median 60 ms (20 samples of the probe Group's two
Bots, and 20 of one Bot, at most 114 ms). This is about ten times the worst
(docs/research/2026-10-02-settle.md).
"""

_UNREADABLE: tuple[type[Exception], ...] = (CodecError, ProtocolError, OSError)
"""What a status poll raises when the Instance gives no readable answer.

An OSError is a refused, reset or closed connection (ConnectionError) or no answer in time
(TimeoutError).
"""


class PlayersStillOnline(Exception):  # noqa: N818 - says what it found, as TimeoutError does
    """The deadline passed with players still online.

    Its message says how many, after how long, and who: "2 players still online after
    waiting 2 s: watcher, control".

    Attributes:
        online: How many players the last status said were online.
        names: The names that status listed, if it listed any.
        deadline_s: How long was waited, in seconds.
    """

    def __init__(self, online: int, names: Sequence[str], deadline_s: float) -> None:
        """Record what the last status said when `deadline_s` seconds had passed."""
        players = f"{online} player{'' if online == 1 else 's'}"
        text = f"{players} still online after waiting {deadline_s:g} s"
        super().__init__(f"{text}: {', '.join(names)}" if names else text)
        self.online = online
        self.names = tuple(names)
        self.deadline_s = deadline_s


async def until_no_player_online(
    endpoint: Endpoint, *, deadline_s: float = SETTLE_TIMEOUT_S
) -> None:
    """Return once the status of the Instance at `endpoint` says no player is online.

    It polls every `SETTLE_INTERVAL_S`, on a connection of its own that it closes
    (`players.online` is the status's count). A status that cannot be read counts as
    empty: refused, closed, late, not a status, or without an integer `players.online`.
    Whatever plays next meets the same failure and reports it.

    The deadline is checked between polls, not by cancelling one, and each poll bounds
    itself by `deadline_s` too, so a server that never answers costs at most two. A poll
    cancelled from outside (a Run cut short) still leaves no socket open: asyncio closes a
    socket cut off while it connects, and the poll closes its Bot in a `finally` once it
    has connected.

    Raises:
        PlayersStillOnline: The last status still said so after `deadline_s` seconds.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + deadline_s
    while True:
        reading = await _players_online(endpoint, timeout_s=deadline_s)
        if reading is None or reading.online == 0:
            return
        if loop.time() >= deadline:
            raise PlayersStillOnline(reading.online, reading.names, deadline_s)
        await asyncio.sleep(SETTLE_INTERVAL_S)


@dataclasses.dataclass(frozen=True, slots=True)
class _Reading:
    """What a status said of the players online: how many, and the names it listed."""

    online: int
    names: tuple[str, ...]


async def _players_online(endpoint: Endpoint, *, timeout_s: float) -> _Reading | None:
    """The players the status at `endpoint` says are online, or None if it gives no readable one."""
    transcript = Transcript(group_id="settle", server="")  # discarded
    try:
        bot = await Bot.connect(
            endpoint, TARGET, name="settle", transcript=transcript, timeout_s=timeout_s
        )
    except _UNREADABLE:
        return None
    try:
        reply = await bot.status()
    except _UNREADABLE:
        return None
    finally:
        await bot.close()
    players: object = reply.get("players")
    if not isinstance(players, dict):
        return None
    fields = {str(key): value for key, value in players.items()}
    online = fields.get("online")
    if not isinstance(online, int) or isinstance(online, bool):
        return None
    return _Reading(online=online, names=_names(fields.get("sample")))


def _names(sample: object) -> tuple[str, ...]:
    """The player names a status `players.sample` lists; whatever else it holds is ignored."""
    names: list[str] = []
    for entry in sample if isinstance(sample, list) else ():
        name = (
            {str(key): value for key, value in entry.items()}.get("name")
            if isinstance(entry, dict)
            else None
        )
        if isinstance(name, str):
            names.append(name)
    return tuple(names)
