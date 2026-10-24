"""Research only: on which side of a step's barrier an open chest shows a hopper's item.

Usage: hopper_slot.py PLAYS OUT.jsonl [--stress N]

Made for #41. Boots one vanilla Instance and plays a draft Group PLAYS times on it. Each play
freezes the world, builds a chest and a hopper with one stone that faces into it, has the
watcher open the chest in a window of its own, then steps the world 3 ticks, one at a time, in
a window that compares `container_set_slot`. The hopper moves its stone on the first step, in
the block entities' part of the tick, after the players ticked; the chest's menu sends the
change from the watcher's own tick (`ServerPlayer.tick` → `broadcastChanges`), the next one,
which runs in the frozen world too (docs/research/2026-10-24-hoppers.md).

Prints one line per play and appends it to OUT.jsonl as JSON: the tick each of the watcher's
`container_set_slot` for the chest landed on, as the step Marks place it (the Comparison's
`_Ticks`), and for the first one, in ms: after Control sent `tick step 1` (`after_step`),
before the watcher sent its first barrier request after that (`before_ask`; negative if it
came after the request), and before the watcher's Mark `tick:1 watcher` (`before_mark`).
A play is `ok` when the watcher was sent exactly one slot, on tick 1. `--stress N` runs N
busy-loop processes beside it.
"""

import argparse
import asyncio
import contextlib
import importlib.util
import json
import shutil
import sys
import tempfile
import types
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from mscts import install
from mscts.adapters.vanilla import VanillaAdapter
from mscts.bot import Face, status_probe
from mscts.cache import cache_dir
from mscts.codec.packets import Direction
from mscts.compare import OBSERVE_OPEN, TICK_MARK
from mscts.group import Group, GroupContext, GroupKind
from mscts.groups._world import CONTROL_AT, fast_forward, join_at_spawn, pin_joins
from mscts.run import run_group
from mscts.runner import free_endpoint, running
from mscts.spec import CONTROL_PLAYER, ServerSpec
from mscts.target import TARGET
from mscts.transcript import Transcript

READY_TIMEOUT_S = 120.0
STOP_TIMEOUT_S = 30.0
BOT_TIMEOUT_S = 30.0
WATCHER = "watcher"
CHEST = (4, -60, 8)
HOPPER = "3 -60 8"
WATCHER_AT = "4.5 -60 5.5"
STEPS = 3
SLOT = "minecraft:container_set_slot"
REQUEST = "minecraft:client_command"
STEP = "tick step 1"
CLEAR = "fill 1 -60 1 15 -57 15 minecraft:air"
RECHECK_TICKS = 5
"""An open chest schedules a recheck of its openers 5 ticks on (`ContainerOpenersCounter`)."""


def _load_script(path: Path) -> types.ModuleType:
    """Import the Python file at `path` by its path, as a module of its own."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


repeat = _load_script(Path(__file__).resolve().parents[1] / "repeat.py")  # its stress_load


async def _probe(context: GroupContext) -> None:
    """Build, open the chest, step 3 ticks in a window, close, and undo it all."""
    control = context.control
    x, y, z = CHEST
    async with contextlib.AsyncExitStack() as undo:
        await pin_joins(control, undo)
        await control.run(f"tp {CONTROL_PLAYER} {CONTROL_AT}")
        watcher = await join_at_spawn(context, undo, WATCHER)
        await control.run("gamerule random_tick_speed 0")
        undo.push_async_callback(control.run, "gamerule random_tick_speed 3")
        undo.push_async_callback(control.run, CLEAR)
        undo.push_async_callback(control.run, f"{CLEAR} strict")
        await context.freeze()
        await control.run(f"setblock {x} {y} {z} minecraft:chest")
        stone = '{Items:[{Slot:0b,id:"minecraft:stone",count:1}]}'
        await control.run(f"setblock {HOPPER} minecraft:hopper[facing=east]{stone}")
        await control.run(f"tp {WATCHER} {WATCHER_AT}")
        async with context.observe(
            "minecraft:open_screen", "minecraft:container_set_content", SLOT
        ):
            await watcher.place(x, y, z, Face.UP)
        async with context.observe(SLOT):
            await context.step(STEPS)
        await watcher.close_container()
        await watcher.sync()
        await fast_forward(control, RECHECK_TICKS)


PROBE = Group(id="research/hopper-slot", run=_probe, kind=GroupKind.TICK_EXACT)


@dataclass(frozen=True, slots=True)
class Seen:
    """What one play's Transcript shows of the chest's slot packets; times in ms."""

    play: int
    ok: bool
    ticks: list[int]
    after_step: float | None
    before_ask: float | None
    before_mark: float | None


def _ms(t_ns: int) -> float:
    return round(t_ns / 1e6, 1)


def seen(transcript: Transcript, play: int) -> Seen:
    """Where the watcher's chest slots landed in the stepped window of `transcript`."""
    opens = [m.t_ns for m in transcript.marks if m.label.startswith(OBSERVE_OPEN)]
    stepped = opens[1]
    ends = sorted(
        (int(m.label.removeprefix(TICK_MARK).split()[0]), m.t_ns)
        for m in transcript.marks
        if m.label.startswith(TICK_MARK) and m.label.endswith(f" {WATCHER}")
    )
    events = [e for e in transcript.events if e.t_ns >= stepped]
    slots = [
        e.t_ns
        for e in events
        if e.bot == WATCHER
        and e.packet.direction is Direction.CLIENTBOUND
        and e.packet.name == SLOT
        and (e.packet.fields or {}).get("window_id") != 0
    ]
    ticks = [next((k for k, end in ends if t < end), len(ends) + 1) for t in slots]
    if not slots:
        return Seen(play, ok=False, ticks=[], after_step=None, before_ask=None, before_mark=None)
    first = slots[0]
    step = next(
        e.t_ns
        for e in events
        if e.bot == CONTROL_PLAYER
        and e.packet.direction is Direction.SERVERBOUND
        and (e.packet.fields or {}).get("command") == STEP
    )
    ask = next(
        e.t_ns
        for e in events
        if e.bot == WATCHER
        and e.packet.direction is Direction.SERVERBOUND
        and e.packet.name == REQUEST
        and e.t_ns > step
    )
    return Seen(
        play,
        ok=ticks == [1],
        ticks=ticks,
        after_step=_ms(first - step),
        before_ask=_ms(ask - first),
        before_mark=_ms(ends[0][1] - first),
    )


async def probe(workdir: Path, plays: int, out: Path) -> int:
    """Boot one vanilla Instance in `workdir`, play the probe `plays` times; count the misses."""
    adapter = VanillaAdapter()
    installation = install.require(adapter, TARGET, cache_dir())
    endpoint = free_endpoint()
    plan = adapter.prepare(
        installation, ServerSpec(host=endpoint.host, port=endpoint.port), workdir
    )
    missed = 0
    async with running(
        plan,
        ready=status_probe(TARGET),
        ready_timeout=READY_TIMEOUT_S,
        stop_timeout=STOP_TIMEOUT_S,
    ) as instance:
        for number in range(plays):
            transcript = await run_group(
                PROBE, instance.endpoint, server="vanilla", timeout_s=BOT_TIMEOUT_S
            )
            row = seen(transcript, number)
            missed += not row.ok
            print(row, flush=True)
            with out.open("a", encoding="utf-8") as sink:
                sink.write(json.dumps(asdict(row)) + "\n")
    return missed


def main(argv: Sequence[str] | None = None) -> int:
    """Run the probe; print how many plays did not get one slot on tick 1."""
    parser = argparse.ArgumentParser(prog="hopper_slot.py", description=__doc__)
    parser.add_argument("plays", type=int)
    parser.add_argument("out", type=Path)
    parser.add_argument("--stress", type=int, default=0, metavar="N")
    args = parser.parse_args(argv)
    workdir = Path(tempfile.mkdtemp(prefix="mscts-research-hopper-slot-"))
    try:
        with repeat.stress_load(args.stress, uuid.uuid4().hex):
            missed = asyncio.run(probe(workdir / "vanilla", args.plays, args.out))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    print("done", args.plays, "plays;", missed, "not on tick 1", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
