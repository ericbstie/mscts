"""Research only: does a server answer a statistics request only after the Bot's earlier action?

Usage: stats_order.py ADAPTER ROUNDS OUT_DIR [--stress N]

Made for #376 (docs/research/2026-10-17-stats-order.md). `GroupContext.step_after` takes the
answers to the statistics requests a Bot sends after its action (`Bot.wait_until_handled`) as
proof that the server has handled the action. This boots one Instance of ADAPTER in creative
mode, freezes the world, and plays ROUNDS rounds: the digger places stone on top of a stone
block (`use_item_on`), then `context.step_after(digger)`, then Control puts air back. Both
vanilla and Pumpkin send the placed cell's `block_update` to the digger from inside their
`use_item_on` handler, so on a server that answers the requests in the order it handles the
packets, that `block_update` arrives before the last answer.

Prints one JSON line per round: whether it was in order, and the times in ms after the place
of the effect and of each answer `wait_until_handled` took (those before Control's
`tick step 1`). A last line counts the rounds in order. If a round was out of order, the
whole Transcript is saved as OUT_DIR/<adapter>-<pid>.jsonl (`probe_loop.save`'s format).
`--stress N` runs N busy-loop processes beside it. Run it under the live lock:

    mise exec -- uv run python scripts/live_lock.py -- \
        mise exec -- uv run python scripts/research/stats_order.py pumpkin 100 /tmp/out
"""

import argparse
import asyncio
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import types
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from mscts import install
from mscts.bot import Bot, Face, status_probe
from mscts.cache import cache_dir
from mscts.cli import ADAPTERS
from mscts.codec.packets import Direction
from mscts.group import Group, GroupContext
from mscts.run import GroupError, run_group
from mscts.runner import free_endpoint, running
from mscts.spec import CONTROL_PLAYER, GameMode, ServerSpec
from mscts.target import TARGET
from mscts.transcript import Event, Transcript

READY_TIMEOUT_S = 120.0
STOP_TIMEOUT_S = 30.0
BOT_TIMEOUT_S = 30.0
DIGGER = "digger"
DIGGER_AT, CONTROL_AT = "8.5 -60 4.5", "4.5 -60 4.5"
"""Where `blocks/place` puts them: the digger 2.5 blocks north of the target, Control clear."""

type Cell = tuple[int, int, int]

TARGET_CELL: Cell = (8, -59, 7)
"""The stone block the digger places onto, on its top face."""

PLACED_CELL: Cell = (8, -58, 7)
"""Where the stone the digger places goes."""

STEP = "tick step 1"
AIR = 0


def _load_script(path: Path) -> types.ModuleType:
    """Import the Python file at `path` by its path, as a module of its own."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_SCRIPTS = Path(__file__).resolve().parents[1]
repeat = _load_script(_SCRIPTS / "repeat.py")  # its stress_load, with the leak guard
probe_loop = _load_script(_SCRIPTS / "research" / "probe_loop.py")  # its save


def _at(cell: Cell) -> str:
    return " ".join(str(coordinate) for coordinate in cell)


def _creative(spec: ServerSpec) -> ServerSpec:
    return replace(spec, game_mode=GameMode.CREATIVE)


async def _stage(context: GroupContext) -> Bot:
    """Join the digger, put it and Control in place, set the target and the stone, freeze."""
    control = context.control
    digger = await context.bot(DIGGER)
    await digger.join()
    for player, at in ((DIGGER, DIGGER_AT), (CONTROL_PLAYER, CONTROL_AT)):
        await control.run(f"tp {player} {at} 0 0")
    await digger.sync()
    position = digger.position
    await digger.move(position.x, position.y, position.z, on_ground=True)
    await control.run(f"setblock {_at(TARGET_CELL)} minecraft:stone")
    await control.run(f"item replace entity {DIGGER} hotbar.0 with minecraft:stone 64")
    await context.freeze()
    return digger


async def _round(context: GroupContext, digger: Bot) -> None:
    """Place the stone and step after it, then put air back and wait until the digger has it."""
    x, y, z = TARGET_CELL
    await digger.place(x, y, z, Face.UP)
    await context.step_after(digger)
    await context.control.run(f"setblock {_at(PLACED_CELL)} minecraft:air")
    await digger.sync()


def order_group(count: int) -> Group:
    """The probe as a Group: `count` rounds after the stage."""

    async def play(context: GroupContext) -> None:
        digger = await _stage(context)
        for _ in range(count):
            await _round(context, digger)

    return Group(id="research/stats-order", run=play, spec=_creative)


def _of(transcript: Transcript, bot: str, name: str, direction: Direction) -> list[Event]:
    return [
        event
        for event in transcript.events
        if event.bot == bot and event.packet.name == name and event.packet.direction is direction
    ]


def _fields(event: Event) -> dict[str, object]:
    return dict(event.packet.fields or {})


def _turns_placed_cell_to_a_block(event: Event) -> bool:
    x, y, z = PLACED_CELL
    fields = _fields(event)
    return fields.get("pos") == {"x": x, "y": y, "z": z} and fields.get("block_state") != AIR


def _ms(t_ns: int | None) -> float | None:
    return None if t_ns is None else round(t_ns / 1e6, 2)


@dataclass(frozen=True, slots=True)
class Round:
    """What one round's Transcript shows, in ns after the digger's `use_item_on`.

    Attributes:
        effect_ns: When the placed cell's `block_update` (not air) reached the digger, before
            the next round's place; None if none came.
        answers_ns: When each `award_stats` reached the digger between the place and Control's
            `tick step 1`: the answers `wait_until_handled` took.
    """

    effect_ns: int | None
    answers_ns: tuple[int, ...]

    @property
    def in_order(self) -> bool:
        """The effect arrived before the last answer `wait_until_handled` took."""
        return (
            self.effect_ns is not None
            and bool(self.answers_ns)
            and self.effect_ns < self.answers_ns[-1]
        )

    def row(self) -> dict[str, object]:
        """The round as a JSON-ready row, in ms."""
        return {
            "in_order": self.in_order,
            "effect_ms": _ms(self.effect_ns),
            "answers_ms": [_ms(answer) for answer in self.answers_ns],
        }


def rounds(transcript: Transcript) -> list[Round]:
    """Each round of `transcript`: one per `use_item_on` the digger sent."""
    places = [
        e.t_ns for e in _of(transcript, DIGGER, "minecraft:use_item_on", Direction.SERVERBOUND)
    ]
    steps = [
        e.t_ns
        for e in _of(transcript, CONTROL_PLAYER, "minecraft:chat_command", Direction.SERVERBOUND)
        if _fields(e).get("command") == STEP
    ]
    effects = [
        e.t_ns
        for e in _of(transcript, DIGGER, "minecraft:block_update", Direction.CLIENTBOUND)
        if _turns_placed_cell_to_a_block(e)
    ]
    answers = [
        e.t_ns for e in _of(transcript, DIGGER, "minecraft:award_stats", Direction.CLIENTBOUND)
    ]
    found = []
    for place, after in zip(places, [*places[1:], None], strict=True):
        step = next((t for t in steps if t > place), None)
        effect = next((t for t in effects if t > place and (after is None or t < after)), None)
        taken = tuple(t - place for t in answers if place < t and (step is None or t < step))
        found.append(Round(effect_ns=None if effect is None else effect - place, answers_ns=taken))
    return found


@dataclass(frozen=True, slots=True)
class Plan:
    """What one run does: the server, the number of rounds, and where a Transcript goes."""

    server: str
    count: int
    out_dir: Path


async def probe(plan: Plan, workdir: Path) -> Transcript | GroupError:
    """Boot one Instance of `plan.server` in `workdir`, play the probe once, and stop it."""
    adapter = ADAPTERS[plan.server]()
    installation = install.require(adapter, TARGET, cache_dir())
    group = order_group(plan.count)
    endpoint = free_endpoint()
    spec = group.spec(ServerSpec(host=endpoint.host, port=endpoint.port))
    prepared = adapter.prepare(installation, spec, workdir)
    async with running(
        prepared,
        ready=status_probe(TARGET),
        ready_timeout=READY_TIMEOUT_S,
        stop_timeout=STOP_TIMEOUT_S,
    ) as instance:
        try:
            return await run_group(
                group, instance.endpoint, server=plan.server, timeout_s=BOT_TIMEOUT_S
            )
        except GroupError as error:
            return error


def report(plan: Plan, played: Transcript | GroupError) -> None:
    """Print each round and the count in order; save the Transcript if any round was not."""
    transcript = played.transcript if isinstance(played, GroupError) else played
    found = rounds(transcript)
    for number, seen in enumerate(found):
        print(json.dumps({"round": number, **seen.row()}), flush=True)
    in_order = sum(seen.in_order for seen in found)
    if isinstance(played, GroupError):
        print(f"{plan.server}: the probe raised: {played}", flush=True)
    if in_order < len(found) or isinstance(played, GroupError):
        path = plan.out_dir / f"{plan.server}-{os.getpid()}.jsonl"
        probe_loop.save(transcript, path)
        print(f"saved {path}", flush=True)
    print(f"{plan.server}: {in_order} of {len(found)} rounds in order", flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the probe and print what it saw; a completed probe exits zero."""
    parser = argparse.ArgumentParser(prog="stats_order.py", description=__doc__)
    parser.add_argument("adapter", choices=sorted(ADAPTERS))
    parser.add_argument("rounds", type=int)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--stress", type=int, default=0, metavar="N")
    args = parser.parse_args(argv)
    plan = Plan(args.adapter, args.rounds, args.out_dir)
    workdir = Path(tempfile.mkdtemp(prefix="mscts-research-stats-order-"))
    try:
        with repeat.stress_load(args.stress, uuid.uuid4().hex):
            played = asyncio.run(probe(plan, workdir / "i"))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    report(plan, played)
    return 0


if __name__ == "__main__":
    sys.exit(main())
