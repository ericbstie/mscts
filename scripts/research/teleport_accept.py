"""Research only: join a Bot, have Control `tp` it at once, and record the accepts.

Usage: teleport_accept.py ADAPTER PLAYS [--stale]

Made for #402 (docs/research/2026-10-16-teleport-accept.md). This boots one Instance of ADAPTER
at the default ServerSpec and plays PLAYS times what `_arena` and `join_at_spawn` do: a new Bot
joins, and Control runs `tp <bot> 0.5 -60 0.5` as soon as `bot.join()` returns. The Bot then
passes `sync`, waits a moment and drains what has arrived.

Each play prints one JSON line: the Bot's `player_position` (`S>B`) and `accept_teleportation`
(`B>S`) in arrival order, each with its teleport id and its time in ms since the Bot's first
packet; the time Control sent the `tp`; the text of the server's `disconnect`, if one came; and
the error the Bot raised, if any. A last line counts the plays the server disconnected.

With `--stale`, the Bot's accept of teleport 2 is dropped (in this script only), and the Bot
sends `accept_teleportation` with id 1 instead, the id the server has replaced. That is how a
server treats the race in #402, where it handles the accept of teleport 1 after the `tp` has set
teleport 2. A server that ignores a stale id (vanilla) disconnects no one; one that keeps a
single pending teleport (Pumpkin) does.
"""

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from mscts import install
from mscts.bot import Bot, status_probe
from mscts.cache import cache_dir
from mscts.cli import ADAPTERS
from mscts.codec.packets import Direction
from mscts.group import GroupContext
from mscts.runner import free_endpoint, running
from mscts.spec import CONTROL_PLAYER, ServerSpec
from mscts.target import TARGET
from mscts.transcript import Transcript

READY_TIMEOUT_S = 120.0
STOP_TIMEOUT_S = 30.0
BOT_TIMEOUT_S = 30.0
TP_AT = "0.5 -60 0.5"
SETTLE_S = 0.5
"""How long the Bot waits after `sync`, so that a disconnect has time to arrive."""
PLAYER_POSITION = "minecraft:player_position"
ACCEPT = "minecraft:accept_teleportation"
CHAT_COMMAND = "minecraft:chat_command"
DISCONNECT = "minecraft:disconnect"
SEND = "send"


@dataclass(frozen=True, slots=True)
class Plan:
    """What one run does: the server, the number of plays, and whether to send a stale accept."""

    server: str
    plays: int
    stale: bool


def play_row(transcript: Transcript, name: str, error: str | None) -> dict[str, object]:
    """What `transcript` shows of Bot `name`'s teleports, accepts and disconnect, and `error`."""
    own = [event for event in transcript.events if event.bot == name]
    start = own[0].t_ns if own else 0
    events: list[dict[str, object]] = []
    kick = None
    for event in own:
        packet = event.packet
        at = round((event.t_ns - start) / 1e6, 2)
        teleport_id = (packet.fields or {}).get("teleport_id")
        if packet.name == PLAYER_POSITION:
            events.append({"ms": at, "dir": "S>B", "teleport": teleport_id})
        elif packet.name == ACCEPT:
            events.append({"ms": at, "dir": "B>S", "accept": teleport_id})
        elif packet.name == DISCONNECT and packet.direction is Direction.CLIENTBOUND:
            kick = packet.payload.decode("utf-8", errors="replace")
    tp_sent = next(
        (
            round((event.t_ns - start) / 1e6, 2)
            for event in transcript.events
            if event.bot == CONTROL_PLAYER
            and event.packet.name == CHAT_COMMAND
            and (event.packet.fields or {}).get("command") == f"tp {name} {TP_AT}"
        ),
        None,
    )
    return {"bot": name, "tp_sent_ms": tp_sent, "events": events, "kick": kick, "error": error}


def drop_accept_of_teleport_2(bot: Bot) -> None:
    """Make `bot`'s Connection send no `accept_teleportation` with id 2, from now on."""
    connection = bot._connection  # noqa: SLF001
    send = connection.send

    async def send_unless_teleport_2(packet_name: str, /, **fields: object) -> None:
        if packet_name == ACCEPT and fields.get("teleport_id") == 2:  # noqa: PLR2004
            return
        await send(packet_name, **fields)

    setattr(connection, SEND, send_unless_teleport_2)


async def send_stale_accept(bot: Bot) -> None:
    """Send `accept_teleportation` with id 1 at the pose `bot` has now."""
    pose = bot.position
    connection = bot._connection  # noqa: SLF001
    await connection.send(
        ACCEPT, teleport_id=1, x=pose.x, y=pose.y, z=pose.z, yaw=pose.yaw, pitch=pose.pitch
    )


async def one_play(
    context: GroupContext, transcript: Transcript, name: str, *, stale: bool
) -> dict[str, object]:
    """Join `name`, have Control `tp` it, and return the row of what the server did."""
    bot = await context.bot(name)
    error = None
    try:
        await bot.join()
        if stale:
            drop_accept_of_teleport_2(bot)
        await context.control.run(f"tp {name} {TP_AT}")
        await bot.sync()
        if stale:
            await send_stale_accept(bot)
        await asyncio.sleep(SETTLE_S)
        await bot.drain()
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {str(exc)[:200]}"
    row = play_row(transcript, name, error)
    await bot.close()
    return row


async def probe(plan: Plan, workdir: Path) -> int:
    """Boot one Instance, print one row per play, and return how many plays were disconnected."""
    adapter = ADAPTERS[plan.server]()
    installation = install.require(adapter, TARGET, cache_dir())
    endpoint = free_endpoint()
    prepared = adapter.prepare(
        installation, ServerSpec(host=endpoint.host, port=endpoint.port), workdir
    )
    transcript = Transcript(group_id="research/teleport-accept", server=plan.server)
    disconnected = 0
    async with running(
        prepared,
        ready=status_probe(TARGET),
        ready_timeout=READY_TIMEOUT_S,
        stop_timeout=STOP_TIMEOUT_S,
    ) as instance:
        context = GroupContext(instance.endpoint, transcript, timeout_s=BOT_TIMEOUT_S)
        try:
            for play in range(plan.plays):
                row = await one_play(context, transcript, f"tp{play:02d}x", stale=plan.stale)
                disconnected += bool(row["kick"] or row["error"])
                print(json.dumps({"play": play, **row}), flush=True)
        finally:
            await context.close()
    return disconnected


def main(argv: Sequence[str] | None = None) -> int:
    """Run the probe, then print how many plays the server disconnected."""
    parser = argparse.ArgumentParser(prog="teleport_accept.py", description=__doc__)
    parser.add_argument("adapter", choices=sorted(ADAPTERS))
    parser.add_argument("plays", type=int)
    parser.add_argument("--stale", action="store_true")
    args = parser.parse_args(argv)
    plan = Plan(args.adapter, args.plays, args.stale)
    workdir = Path(tempfile.mkdtemp(prefix="mscts-research-teleport-accept-"))
    try:
        disconnected = asyncio.run(probe(plan, workdir / "i"))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    print(f"{plan.server}: {disconnected} of {plan.plays} plays disconnected", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
