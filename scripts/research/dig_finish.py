"""Research only: find why vanilla breaks a block a player finished early only some of the time.

Usage: dig_finish.py OUT.jsonl

Made for #347. Boots one vanilla Instance, joins a digger and a watcher, freezes the world,
and digs a block in survival: in each case the digger sends the START and the STOP one client
tick apart, far too early for the block, at a cell no START has named before. The cases differ
in how long the digger has been alive (since its last respawn) when it sends the START, and in
the block and tool. After each STOP it waits, reads everything the server sent, and puts air
back, which disarms a delayed destroy on the digger's next tick.

It tells apart three explanations for the early finishes PR #343 saw accepted:

- (a) a STOP judged against an older START: every case digs a fresh cell, so none can be;
- (b) the delayed destroy a refused STOP arms (`ServerPlayerGameMode.tick`): it breaks the
  block a tick or more after the STOP, and tells the watcher a crack stage of 10 or more
  first, where an accepted STOP tells it -1 (255 on the network);
- (c) the 60-tick `hasClientLoaded` gate: a STOP it drops gets no `block_changed_ack`.

Prints one line per case and appends it to OUT.jsonl as JSON. Ages are seconds from the
digger's `respawn` to its START, both as the Bot's Transcript recorded them.
"""

import argparse
import asyncio
import contextlib
import json
import shutil
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from mscts import install
from mscts.adapters.vanilla import VanillaAdapter
from mscts.bot import Bot, Face, status_probe
from mscts.cache import cache_dir
from mscts.codec.packets import Direction
from mscts.group import Group, GroupContext
from mscts.run import run_group
from mscts.runner import free_endpoint, running
from mscts.spec import CONTROL_PLAYER, ServerSpec
from mscts.target import TARGET
from mscts.transcript import Event, Transcript

READY_TIMEOUT_S = 120.0
STOP_TIMEOUT_S = 30.0
BOT_TIMEOUT_S = 30.0
DIGGER, WATCHER = "digger", "watcher"
DIGGER_AT, WATCHER_AT, CONTROL_AT = "8.5 -60 4.5", "12.5 -60 4.5", "4.5 -60 4.5"
STONE, OBSIDIAN = "minecraft:stone", "minecraft:obsidian"
HAND, DIAMOND_PICKAXE = "minecraft:air", "minecraft:diamond_pickaxe"
START, STOP = 0, 3
"""`ServerboundPlayerActionPacket.Action` ordinals."""

type Cell = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class Case:
    """One early finish: the cell, what is there and in hand, and when the START goes.

    `age_s` is how long after the digger's last respawn the START is sent; `respawn` kills
    and respawns the digger first; `watch_s` is how long the probe waits for a break.
    """

    name: str
    cell: Cell
    block: str
    tool: str
    age_s: float
    watch_s: float
    respawn: bool


CASES = (
    Case("stone, just respawned", (6, -60, 6), STONE, HAND, 0.0, 10.0, respawn=True),
    Case("stone, the same life, 11 s on", (7, -60, 6), STONE, HAND, 11.0, 1.0, respawn=False),
    Case("stone, 4 s", (8, -60, 6), STONE, HAND, 4.0, 1.5, respawn=True),
    Case("stone, 6 s", (9, -60, 6), STONE, HAND, 6.0, 1.0, respawn=False),
    Case("stone, 9 s", (10, -60, 6), STONE, HAND, 9.0, 1.0, respawn=False),
    Case("obsidian, 5 s", (6, -60, 7), OBSIDIAN, DIAMOND_PICKAXE, 5.0, 1.5, respawn=True),
    Case("obsidian, 12 s", (7, -60, 7), OBSIDIAN, DIAMOND_PICKAXE, 12.0, 1.0, respawn=False),
)
"""Obsidian is dug with a diamond pickaxe, the tool it needs, so that only the time is wrong."""


def _at(cell: Cell) -> str:
    return " ".join(str(coordinate) for coordinate in cell)


async def _respawn(context: GroupContext, digger: Bot) -> float:
    """Kill the digger, respawn it where it stood, and return when it was respawned."""
    await context.control.run(f"kill {DIGGER}")
    await digger.respawn()
    born = time.monotonic()
    await context.control.run(f"tp {DIGGER} {DIGGER_AT} 0 0")
    await digger.sync()
    position = digger.position
    await digger.move(position.x, position.y, position.z, on_ground=True)
    return born


async def _dig_early(context: GroupContext, bots: tuple[Bot, Bot], case: Case, born: float) -> None:
    """Set the case up, wait for its age, START then STOP, watch, then put air back."""
    digger, watcher = bots
    control = context.control
    await control.run(f"setblock {_at(case.cell)} {case.block}")
    await control.run(f"item replace entity {DIGGER} hotbar.0 with {case.tool}")
    await asyncio.sleep(max(0.0, born + case.age_s - time.monotonic()))
    x, y, z = case.cell
    await digger.dig(x, y, z, Face.NORTH)
    await digger.stop_digging(x, y, z, Face.NORTH)
    await asyncio.sleep(case.watch_s)
    await digger.sync()
    await watcher.sync()
    await control.run(f"setblock {_at(case.cell)} minecraft:air")
    await control.run("kill @e[type=minecraft:item]")
    await context.step(1)


async def _probe(context: GroupContext) -> None:
    control = context.control
    digger = await context.bot(DIGGER)
    await digger.join()
    watcher = await context.bot(WATCHER)
    await watcher.join()
    for player, at in ((DIGGER, DIGGER_AT), (WATCHER, WATCHER_AT), (CONTROL_PLAYER, CONTROL_AT)):
        await control.run(f"tp {player} {at} 0 0")
    await digger.sync()
    async with contextlib.AsyncExitStack() as undo:
        undo.push_async_callback(control.run, "gamerule random_tick_speed 3")
        await control.run("gamerule random_tick_speed 0")
        await context.freeze()
        born = time.monotonic()
        for case in CASES:
            if case.respawn:
                born = await _respawn(context, digger)
            await _dig_early(context, (digger, watcher), case, born)


PROBE = Group(id="research/dig-finish", run=_probe)


def _at_cell(event: Event, cell: Cell) -> bool:
    x, y, z = cell
    return (event.packet.fields or {}).get("pos") == {"x": x, "y": y, "z": z}


def _field(event: Event, name: str) -> object:
    return (event.packet.fields or {}).get(name)


def _of(transcript: Transcript, bot: str, name: str, direction: Direction) -> list[Event]:
    return [
        event
        for event in transcript.events
        if event.bot == bot and event.packet.name == name and event.packet.direction is direction
    ]


@dataclass(frozen=True, slots=True)
class Seen:
    """What one case's Transcript shows.

    Attributes:
        case: The case's name.
        age_s: Seconds from the digger's last `respawn` to its START.
        ack: Whether the STOP's sequence got a `block_changed_ack`.
        broke_ms: When the digger was sent air at the cell, in ms after the STOP, or None.
        stages: The crack stages the watcher was sent for the cell, in order (255 is -1).
    """

    case: str
    age_s: float
    ack: bool
    broke_ms: float | None
    stages: list[int]


def seen(transcript: Transcript, case: Case) -> Seen:
    """Read `case`'s START, STOP, ack, break and cracks out of `transcript`."""
    actions = [
        event
        for event in _of(transcript, DIGGER, "minecraft:player_action", Direction.SERVERBOUND)
        if _at_cell(event, case.cell)
    ]
    start = next(event for event in actions if _field(event, "action") == START)
    stop = next(event for event in actions if _field(event, "action") == STOP)
    born = max(
        event.t_ns
        for event in _of(transcript, DIGGER, "minecraft:respawn", Direction.CLIENTBOUND)
        + _of(transcript, DIGGER, "minecraft:login", Direction.CLIENTBOUND)
        if event.t_ns < start.t_ns
    )
    cleanup = next(
        event.t_ns
        for event in _of(
            transcript, CONTROL_PLAYER, "minecraft:chat_command", Direction.SERVERBOUND
        )
        if event.t_ns > stop.t_ns
        and _field(event, "command") == f"setblock {_at(case.cell)} minecraft:air"
    )
    acks = _of(transcript, DIGGER, "minecraft:block_changed_ack", Direction.CLIENTBOUND)
    updates = [
        event
        for event in _of(transcript, DIGGER, "minecraft:block_update", Direction.CLIENTBOUND)
        if _at_cell(event, case.cell) and stop.t_ns < event.t_ns < cleanup
    ]
    broke = next((event for event in updates if _field(event, "block_state") == 0), None)
    cracks = [
        event
        for event in _of(transcript, WATCHER, "minecraft:block_destruction", Direction.CLIENTBOUND)
        if _at_cell(event, case.cell) and start.t_ns <= event.t_ns < cleanup
    ]
    return Seen(
        case=case.name,
        age_s=round((start.t_ns - born) / 1e9, 2),
        ack=any(_field(ack, "sequence") == _field(stop, "sequence") for ack in acks),
        broke_ms=None if broke is None else round((broke.t_ns - stop.t_ns) / 1e6, 1),
        stages=[int(str(_field(event, "stage"))) for event in cracks],
    )


async def probe(workdir: Path) -> Transcript:
    """Boot one vanilla Instance in `workdir`, play the probe on it once, and stop it."""
    adapter = VanillaAdapter()
    installation = install.require(adapter, TARGET, cache_dir())
    endpoint = free_endpoint()
    plan = adapter.prepare(
        installation, ServerSpec(host=endpoint.host, port=endpoint.port), workdir
    )
    async with running(
        plan,
        ready=status_probe(TARGET),
        ready_timeout=READY_TIMEOUT_S,
        stop_timeout=STOP_TIMEOUT_S,
    ) as instance:
        return await run_group(PROBE, instance.endpoint, server="vanilla", timeout_s=BOT_TIMEOUT_S)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the probe, then print and save what each case shows."""
    parser = argparse.ArgumentParser(prog="dig_finish.py", description=__doc__)
    parser.add_argument("out", type=Path)
    args = parser.parse_args(argv)
    workdir = Path(tempfile.mkdtemp(prefix="mscts-research-dig-finish-"))
    try:
        transcript = asyncio.run(probe(workdir / "vanilla"))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    with args.out.open("a", encoding="utf-8") as sink:
        for case in CASES:
            row = seen(transcript, case)
            print(row, flush=True)
            sink.write(json.dumps(asdict(row)) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
