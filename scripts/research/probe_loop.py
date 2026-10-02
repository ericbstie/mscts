"""Research only: play a Group over and over against two fresh Reference Instances.

Usage: probe_loop.py PLAYS OUT_DIR [--stress N]

Boots two Instances of the vanilla Reference, as the live Self-check does, then plays the
probe Group (`tests/support/probe.py`) PLAYS times on each in turn and judges the pair.
One line per play gives the Verdict and, for each side: when the watcher's first chunk
batch and its chunk (0, 0) arrived, when the window opened and closed, the gaps between
the barrier's answers (`award_stats`) inside the window for each Bot, how long each Bot's
`sync` took, which Bots' `sync` was capped (`sync:capped`), and when the first
`block_update` reached each Bot against the window's close. A play that does not match
has both Transcripts saved in OUT_DIR as `play-<n>-<side>.jsonl` (the Marks, then the
Events; a research format, not a public one). `--stress N` runs N busy-loop processes
beside it. All times are milliseconds from the start of the side's Transcript.
Saved payloads are complete. A finished probe prints play/match totals and Divergences
per test case, and exits zero even if the servers differed. `run(loop=...)` can use
another play loop (#107).

Made for #88, a failure about once in 200 plays, which a quiet machine never showed:
run it beside a looping `mise run check`.
"""

import argparse
import asyncio
import contextlib
import importlib.util
import itertools
import json
import shutil
import struct
import sys
import tempfile
import types
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from mscts import install
from mscts.adapters.vanilla import VanillaAdapter
from mscts.bot import SYNC_CAPPED, status_probe
from mscts.cache import cache_dir
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN, Outcome
from mscts.group import Group
from mscts.net import Endpoint
from mscts.run import GroupError, judge, run_group
from mscts.runner import free_endpoint, running
from mscts.spec import CONTROL_PLAYER, ServerSpec
from mscts.target import TARGET
from mscts.transcript import Transcript

READY_TIMEOUT_S = 120.0  # a cold vanilla boot unpacks bundled libraries and makes a world
STOP_TIMEOUT_S = 30.0
WATCHER = "watcher"
CHUNK = "minecraft:level_chunk_with_light"
BATCH_FINISHED = "minecraft:chunk_batch_finished"
ANSWER = "minecraft:award_stats"
REQUEST = "minecraft:client_command"
BLOCK_UPDATE = "minecraft:block_update"
SIDES = ("a", "b")

type Play = Callable[..., Awaitable[Transcript]]
"""How a Group is played on one Endpoint: `run_group`'s signature."""

type Loop = Callable[[Group, Sequence[Endpoint], int, Path], Awaitable[int]]
"""The play loop `run` uses; returns the number of plays that did not match."""


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
join = _load_script(_SCRIPTS / "research" / "join.py")  # its jsonable


def chunk_xz(payload: bytes) -> tuple[int, int]:
    """The chunk coordinates a `level_chunk_with_light` payload starts with."""
    x, z = struct.unpack(">ii", payload[:8])
    return x, z


def ms(t_ns: int | None) -> float | None:
    """`t_ns` in milliseconds, to a tenth; None stays None."""
    return None if t_ns is None else round(t_ns / 1e6, 1)


@dataclass(frozen=True, slots=True)
class Side:
    """What one side's Transcript shows of the join, the window and its barrier.

    Attributes:
        first_batch_ms: When the watcher's first `chunk_batch_finished` arrived.
        chunk00_ms: When the watcher's chunk (0, 0) arrived.
        chunks: How many chunks the watcher was sent.
        open_ms: When the window opened (None if it did not).
        close_ms: When the window closed (None if it did not).
        gaps_ms: For each Bot, the gaps between its `award_stats` answers inside the window.
        sync_ms: For each Bot, how long its `sync` took: from its first `client_command`
            after the window opened to its last `award_stats` inside it (None if either
            is missing).
        capped: The Bots whose `sync` stopped at `SYNC_MAX_TRIPS`, as its Mark says.
        update_ms: For each Bot, when its first `block_update` after the window opened came.
    """

    first_batch_ms: float | None
    chunk00_ms: float | None
    chunks: int
    open_ms: float | None
    close_ms: float | None
    gaps_ms: dict[str, list[float]]
    sync_ms: dict[str, float | None]
    capped: tuple[str, ...]
    update_ms: dict[str, float | None]

    def update_where(self, bot: str) -> str:
        """Where `bot`'s first `block_update` came: `in` the window, `AFTER_CLOSE`, or `none`."""
        at = self.update_ms.get(bot)
        if at is None:
            return "none"
        if self.close_ms is not None and at > self.close_ms:
            return "AFTER_CLOSE"
        return "in"

    def line(self) -> str:
        """One line: the numbers above, in a fixed order."""
        gaps = " ".join(f"{bot}_gaps={gaps}" for bot, gaps in sorted(self.gaps_ms.items()))
        syncs = " ".join(f"{bot}_sync={took}" for bot, took in sorted(self.sync_ms.items()))
        updates = " ".join(
            f"{bot}_update={self.update_where(bot)}({self.update_ms.get(bot)})"
            for bot in sorted(self.update_ms)
        )
        capped = ",".join(self.capped) or "none"
        return (
            f"first_batch={self.first_batch_ms} chunk00={self.chunk00_ms} chunks={self.chunks} "
            f"open={self.open_ms} close={self.close_ms} {gaps} {syncs} capped={capped} {updates}"
        )


def summarise(transcript: Transcript, *, bots: Sequence[str] = (CONTROL_PLAYER, WATCHER)) -> Side:
    """The `Side` of `transcript`: the watcher's join, and the first window's barrier."""
    opened = next((m.t_ns for m in transcript.marks if m.label.split()[0] == OBSERVE_OPEN), None)
    closed = next((m.t_ns for m in transcript.marks if m.label == OBSERVE_CLOSE), None)
    watcher = [e for e in transcript.events if e.bot == WATCHER]
    first_batch = next((e.t_ns for e in watcher if e.packet.name == BATCH_FINISHED), None)
    chunks = [e for e in watcher if e.packet.name == CHUNK]
    chunk00 = next((e.t_ns for e in chunks if chunk_xz(e.packet.payload) == (0, 0)), None)
    gaps: dict[str, list[float]] = {}
    syncs: dict[str, float | None] = {}
    updates: dict[str, float | None] = {}
    for bot in bots:
        answers = [
            e.t_ns
            for e in transcript.events
            if e.bot == bot
            and e.packet.name == ANSWER
            and opened is not None
            and closed is not None
            and opened <= e.t_ns <= closed
        ]
        gaps[bot] = [round((b - a) / 1e6, 1) for a, b in itertools.pairwise(answers)]
        request = next(
            (
                e.t_ns
                for e in transcript.events
                if e.bot == bot
                and e.packet.name == REQUEST
                and opened is not None
                and e.t_ns >= opened
            ),
            None,
        )
        syncs[bot] = ms(answers[-1] - request) if request is not None and answers else None
        update = next(
            (
                e.t_ns
                for e in transcript.events
                if e.bot == bot
                and e.packet.name == BLOCK_UPDATE
                and opened is not None
                and e.t_ns >= opened
            ),
            None,
        )
        updates[bot] = ms(update)
    return Side(
        first_batch_ms=ms(first_batch),
        chunk00_ms=ms(chunk00),
        chunks=len(chunks),
        open_ms=ms(opened),
        close_ms=ms(closed),
        gaps_ms=gaps,
        sync_ms=syncs,
        capped=tuple(
            m.label.removeprefix(f"{SYNC_CAPPED} ")
            for m in transcript.marks
            if m.label.startswith(f"{SYNC_CAPPED} ")
        ),
        update_ms=updates,
    )


def save(transcript: Transcript, path: Path) -> None:
    """Write `transcript`'s Marks, then its Events, one JSON object per line, to `path`.

    Makes `path`'s directory first, if it is not there.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as sink:
        for mark in transcript.marks:
            sink.write(json.dumps({"mark": mark.label, "t_ns": mark.t_ns}) + "\n")
        for event in transcript.events:
            packet = event.packet
            row = {
                "t_ns": event.t_ns,
                "bot": event.bot,
                "direction": packet.direction.value,
                "state": packet.state.value,
                "name": packet.name,
                "chunk": chunk_xz(packet.payload) if packet.name == CHUNK else None,
                "payload_hex": packet.payload.hex(),
                "fields": join.jsonable(packet.fields) if packet.fields is not None else None,
            }
            sink.write(json.dumps(row) + "\n")


async def loop(
    group: Group,
    endpoints: Sequence[Endpoint],
    plays: int,
    out_dir: Path,
    *,
    play: Play = run_group,
) -> int:
    """Play `group` `plays` times on each of `endpoints` in turn, and judge each pair.

    Prints one line per play, and saves the Transcripts of a play whose Verdict is not
    `match` in `out_dir`. Returns how many plays did not match.
    """
    not_matching = 0
    divergences: Counter[str] = Counter()
    for number in range(plays):
        attempts: list[Transcript | GroupError] = []
        for side, endpoint in zip(SIDES, endpoints, strict=False):
            try:
                attempts.append(await play(group, endpoint, server=side))
            except GroupError as error:
                attempts.append(error)
        verdict = judge(group, attempts[0], attempts[1])
        transcripts = [a.transcript if isinstance(a, GroupError) else a for a in attempts]
        matched = verdict.outcome is Outcome.MATCH
        divergences.update(d.test_case for d in verdict.divergences)
        sides = " | ".join(
            f"{side} {summarise(transcript).line()}"
            for side, transcript in zip(SIDES, transcripts, strict=False)
        )
        print(number, "ok" if matched else "BAD", verdict.outcome.value, "|", sides, flush=True)
        if not matched:
            not_matching += 1
            print("   detail:", str(verdict.detail)[:400], flush=True)
            for side, transcript in zip(SIDES, transcripts, strict=False):
                save(transcript, out_dir / f"play-{number}-{side}.jsonl")
    print(f"totals: {plays} plays, {plays - not_matching} matched", flush=True)
    for name, count in sorted(divergences.items()):
        print(f"  {name}: {count} Divergences", flush=True)
    return not_matching


async def run(group: Group, plays: int, out_dir: Path, workdir: Path, *, loop: Loop = loop) -> int:
    """Boot two vanilla Instances in `workdir`, play `group` `plays` times on them, stop them."""
    adapter = VanillaAdapter()
    installation = install.require(adapter, TARGET, cache_dir())
    plans = []
    for side in SIDES:
        endpoint = free_endpoint()
        spec = ServerSpec(host=endpoint.host, port=endpoint.port)
        plans.append(adapter.prepare(installation, spec, workdir / side))
    async with contextlib.AsyncExitStack() as stack:
        async with asyncio.TaskGroup() as boot:
            tasks = [
                boot.create_task(
                    stack.enter_async_context(
                        running(
                            plan,
                            ready=status_probe(TARGET),
                            ready_timeout=READY_TIMEOUT_S,
                            stop_timeout=STOP_TIMEOUT_S,
                        )
                    )
                )
                for plan in plans
            ]
        endpoints = [task.result().endpoint for task in tasks]
        return await loop(group, endpoints, plays, out_dir)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse `argv` (or sys.argv[1:]); SystemExit(2) on a bad argument."""
    parser = argparse.ArgumentParser(prog="probe_loop.py", description=__doc__)
    parser.add_argument("plays", type=int, help="how many plays on each Instance")
    parser.add_argument("out_dir", type=Path, help="where a failing play's Transcripts go")
    parser.add_argument(
        "--stress", type=int, default=0, metavar="N", help="run N busy-loop processes beside it"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run probe_loop.py; a completed probe exits zero even when plays differ (#107)."""
    args = parse_args(argv)
    probe = _load_script(Path(__file__).resolve().parents[2] / "tests" / "support" / "probe.py")
    workdir = Path(tempfile.mkdtemp(prefix="mscts-research-probe-loop-"))
    try:
        with repeat.stress_load(args.stress, uuid.uuid4().hex):
            not_matching = asyncio.run(
                run(probe.SETBLOCK_OBSERVED, args.plays, args.out_dir, workdir)
            )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    print("done", args.plays, "plays;", not_matching, "not matching", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
