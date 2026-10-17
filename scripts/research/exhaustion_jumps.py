"""Research only: which walking jumps vanilla counts, and how many player ticks lay between.

Usage: exhaustion_jumps.py PLAYS OUT_DIR [--stress N] [--syncs N] [--jumps N]

Made for #354. Plays the jump part of a draft `player/exhaustion` (#57) on two fresh vanilla
Instances, through `probe_loop.py`'s `run`: a fresh exerciser, `--jumps` walking jumps (50,
as in the draft) in one window, then the readback of its food. Each jump is a `jump()` tick,
an airborne move at
y -59.58 (`on_ground` false), `--syncs` barriers (1 by default, as in the draft), a landing
move at y -60, and one barrier.

Every `award_stats` the barrier takes carries the player's dirty statistics: `play_time`,
which `ServerPlayer.doTick` raises each player tick, and `jump`, which
`ServerPlayer.jumpFromGround` raises for each jump the server counts. So for each jump the
probe tells whether the server counted it, and how many player ticks ran from the last
counted jump to it, read off the first answer after each. One line per play and side gives
the counts, a play that does not match has both Transcripts saved in OUT_DIR, and OUT_DIR
`jumps.jsonl` gets one row per jump.
"""

import argparse
import asyncio
import contextlib
import importlib.util
import itertools
import json
import shutil
import sys
import tempfile
import types
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from mscts.codec.packets import Direction
from mscts.codec.wire import Reader
from mscts.compare import Outcome
from mscts.group import Group, GroupContext
from mscts.groups._world import fresh, join_at_spawn, pin_joins
from mscts.groups.player_hunger import (
    _LANE_Z,
    _SET_HEALTH,
    _START_X,
    EXERCISER,
    _operator,
    _read_back,
)
from mscts.net import Endpoint
from mscts.run import GroupError, judge, run_group
from mscts.transcript import Transcript


def _load_script(path: Path) -> types.ModuleType:
    """Import the Python file at `path` by its path, as a module of its own."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_SCRIPTS = Path(__file__).resolve().parents[1]
probe_loop = _load_script(_SCRIPTS / "research" / "probe_loop.py")
repeat = _load_script(_SCRIPTS / "repeat.py")

AIRBORNE_Y = -59.58
GROUND_Y = -60.0
ANSWER = "minecraft:award_stats"
MOVE = "minecraft:move_player_pos"
CUSTOM, PLAY_TIME, JUMP = 8, 1, 23
"""The `custom` stat type, and its `play_time` and `jump` stats (26.3 data generator,
registries.json: `minecraft:stat_type`, `minecraft:custom_stat`)."""


def probe_group(syncs: int, jumps: int) -> Group:
    """The jump part alone, as a Group: `jumps` jumps, `syncs` barriers while it is up."""

    async def run(context: GroupContext) -> None:
        control = context.control
        async with contextlib.AsyncExitStack() as undo:
            await pin_joins(control, undo)
            bot = await join_at_spawn(context, undo, EXERCISER)
            await context.freeze()
            await fresh(context, bot)
            await control.run(f"tp {bot.name} {_START_X} -60 {_LANE_Z} -90 0")
            async with context.observe(_SET_HEALTH):
                for _ in range(jumps):
                    await bot.jump()
                    await bot.move(_START_X, AIRBORNE_Y, _LANE_Z, on_ground=False)
                    for _ in range(syncs):
                        await bot.sync()
                    await bot.move(_START_X, GROUND_Y, _LANE_Z)
                    await bot.sync()
            await _read_back(context, bot)

    return Group(id="research/exhaustion-jumps", run=run, spec=_operator)


@dataclass(frozen=True, slots=True)
class Answer:
    """One `award_stats` the exerciser took: when, and its `play_time` and `jump` values."""

    t_ns: int
    play_time: int | None
    jump: int | None


def stats(payload: bytes) -> dict[tuple[int, int], int]:
    """An `award_stats` payload's entries: (stat type, stat) to value, all VarInts."""
    reader = Reader(payload)
    entries: dict[tuple[int, int], int] = {}
    for _ in range(reader.var_int()):
        kind, stat = reader.var_int(), reader.var_int()
        entries[kind, stat] = reader.var_int()
    return entries


def answers(transcript: Transcript) -> list[Answer]:
    """Every `award_stats` the exerciser took, in order."""
    rows = []
    for event in transcript.events:
        if event.bot == EXERCISER and event.packet.name == ANSWER:
            entries = stats(event.packet.payload)
            rows.append(
                Answer(event.t_ns, entries.get((CUSTOM, PLAY_TIME)), entries.get((CUSTOM, JUMP)))
            )
    return rows


def jump_moves(transcript: Transcript) -> list[int]:
    """When the exerciser sent each airborne move, the move that makes a jump."""
    return [
        event.t_ns
        for event in transcript.events
        if event.bot == EXERCISER
        and event.packet.name == MOVE
        and event.packet.direction is Direction.SERVERBOUND
        and (event.packet.fields or {}).get("y") == AIRBORNE_Y
    ]


@dataclass(frozen=True, slots=True)
class Jump:
    """One jump of one play on one side.

    Attributes:
        index: Which jump, from 0.
        counted: Whether the server counted it (its `jump` stat rose before the next jump).
        ticks: Player ticks from the first answer after the last counted jump to the first
            answer after this one, or None for the first jump or a missing `play_time`.
        cycle: Player ticks from the first answer after the previous jump to the first
            answer after this one, or None as above.
    """

    index: int
    counted: bool
    ticks: int | None
    cycle: int | None


def jumps(transcript: Transcript) -> list[Jump]:
    """Each jump of `transcript`: whether it counted, and the ticks before it."""
    moves = jump_moves(transcript)
    taken = answers(transcript)
    bounds = [*moves, max((a.t_ns for a in taken), default=0) + 1]
    rows: list[Jump] = []
    last_counted: int | None = None
    previous: int | None = None
    for index, (start, end) in enumerate(itertools.pairwise(bounds)):
        inside = [a for a in taken if start < a.t_ns < end]
        first = inside[0].play_time if inside else None
        counted = any(a.jump is not None for a in inside)
        rows.append(
            Jump(
                index=index,
                counted=counted,
                ticks=None if first is None or last_counted is None else first - last_counted,
                cycle=None if first is None or previous is None else first - previous,
            )
        )
        previous = first
        if counted:
            last_counted = first
    return rows


def describe(side: str, rows: Sequence[Jump]) -> str:
    """One line for one side: jumps counted, and missed jumps with their ticks."""
    missed = [(row.index, row.ticks) for row in rows if not row.counted]
    cycles = Counter(row.cycle for row in rows if row.cycle is not None)
    return (
        f"{side} counted={sum(row.counted for row in rows)}/{len(rows)} "
        f"missed(index,ticks)={missed} cycles={dict(sorted(cycles.items()))}"
    )


def log_play(
    out_dir: Path, number: int, transcripts: Sequence[Transcript], *, matched: bool
) -> str:
    """Log each side's jumps in OUT_DIR `jumps.jsonl`; return a line per side.

    Saves both Transcripts of a play that did not match.
    """
    lines = []
    with (out_dir / "jumps.jsonl").open("a", encoding="utf-8") as log:
        for side, transcript in zip(probe_loop.SIDES, transcripts, strict=False):
            rows = jumps(transcript)
            lines.append(describe(side, rows))
            for row in rows:
                log.write(json.dumps({"play": number, "side": side, **asdict(row)}) + "\n")
            if not matched:
                probe_loop.save(transcript, out_dir / f"play-{number}-{side}.jsonl")
    return " | ".join(lines)


async def loop(group: Group, endpoints: Sequence[Endpoint], plays: int, out_dir: Path) -> int:
    """Play `group` `plays` times on each endpoint; print, save and log each play."""
    not_matching = 0
    for number in range(plays):
        attempts: list[Transcript | GroupError] = []
        for side, endpoint in zip(probe_loop.SIDES, endpoints, strict=False):
            try:
                attempts.append(await run_group(group, endpoint, server=side))
            except GroupError as error:
                attempts.append(error)
        verdict = judge(group, attempts[0], attempts[1])
        transcripts = [a.transcript if isinstance(a, GroupError) else a for a in attempts]
        matched = verdict.outcome is Outcome.MATCH
        lines = log_play(out_dir, number, transcripts, matched=matched)
        print(number, "ok" if matched else "BAD", verdict.outcome.value, "|", lines, flush=True)
        if not matched:
            not_matching += 1
            print("   detail:", str(verdict.detail)[:400], flush=True)
    print(f"totals: {plays} plays, {plays - not_matching} matched", flush=True)
    return not_matching


def main(argv: Sequence[str] | None = None) -> int:
    """Run the probe; it exits zero even when plays differ."""
    parser = argparse.ArgumentParser(prog="exhaustion_jumps.py", description=__doc__)
    parser.add_argument("plays", type=int)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--stress", type=int, default=0, metavar="N")
    parser.add_argument("--syncs", type=int, default=1, metavar="N")
    parser.add_argument("--jumps", type=int, default=50, metavar="N")
    args = parser.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="mscts-research-exhaustion-jumps-"))
    try:
        with repeat.stress_load(args.stress, uuid.uuid4().hex):
            not_matching = asyncio.run(
                probe_loop.run(
                    probe_group(args.syncs, args.jumps),
                    args.plays,
                    args.out_dir,
                    workdir,
                    loop=loop,
                )
            )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    print("done", args.plays, "plays;", not_matching, "not matching", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
