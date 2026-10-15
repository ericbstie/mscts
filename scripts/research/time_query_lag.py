"""Research only: how many ticks a `time query gametime` adds after a packet, during a step.

Usage: time_query_lag.py ADAPTER OUT.jsonl [--events N] [--label TEXT] [--burst N]

Made for #387. The `mobs/*` Groups step a frozen world with one `tick step <budget>`, and
when the Bot receives the packet a sample is about, Control reads `time query gametime`
(`mscts.groups.mobs_pathfinding`). While that query travels, the world keeps ticking.

This probe boots one Instance of ADAPTER, joins a Bot, freezes the world, reads the game
time, and steps it far enough for N events. The event is `set_time`, which carries a game
time and comes every 20 ticks: when the Bot receives one (`Bot.expect`), Control reads the
game time exactly as the Groups do. Each row is the packet's game time, the answer's, and
their difference. Events whose answer came after the step ran out are marked, since a
frozen world stops the count. It first checks, in the frozen world, that a `set_time`
carries the same game time as the query, so that the first 8 bytes of its payload are the
game time on that server.

With `--burst N`, Control instead sends N queries back to back during the step, and the
probe reads, on Control's own connection, whether a `set_time` carries the game time from
before its tick moved the clock on or from after. A query is answered between ticks, so:

- if a `set_time` arrives right after an answer and carries that answer's game time, the
  server stamps it before the tick moves the clock on (`before`);
- if a `set_time` arrives right before an answer and carries that answer's game time, the
  server stamps it after (`after`).
"""

import argparse
import asyncio
import collections
import itertools
import json
import os
import secrets
import shutil
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from mscts import install
from mscts.bot import Bot, status_probe
from mscts.cache import cache_dir
from mscts.cli import ADAPTERS
from mscts.codec.packets import Direction, Packet
from mscts.group import Group, GroupContext
from mscts.groups.mobs_pathfinding import gametime
from mscts.run import run_group
from mscts.runner import free_endpoint, running
from mscts.spec import CONTROL_PLAYER, ServerSpec
from mscts.target import TARGET
from mscts.transcript import Transcript

READY_TIMEOUT_S = 120.0
STOP_TIMEOUT_S = 30.0
GROUP_TIMEOUT_S = 600.0
SET_TIME = "minecraft:set_time"
SYSTEM_CHAT = "minecraft:system_chat"
QUERY = "time query gametime"
EVENT_TIMEOUT_S = 10.0
TICKS_PER_EVENT = 20
TICKS_PER_QUERY = 6
JITTER_MS = 100
SPARE_TICKS = 400
"""Ticks the step runs past the last event, so that no counted answer meets its end."""


@dataclass(frozen=True, slots=True)
class Row:
    """One event: the game time `set_time` carried, the query's answer, and the gap.

    `start` is the game time before the step and `budget` its length; `after_step` marks an
    answer at or past the step's end, whose gap is cut short; `wall_ms` is how long the
    query took from the packet's arrival to its answer.
    """

    label: str
    server: str
    start: int
    budget: int
    sent: int
    answer: int
    added: int
    after_step: bool
    wall_ms: float
    load: float


@dataclass(frozen=True, slots=True)
class Stamps:
    """What a burst shows about when a server stamps `set_time`.

    `before` and `after` count the `set_time`s that prove one or the other (see the module
    docstring); `set_times` and `answers` count what Control received during the step.
    `around` counts, for each `set_time` between two answers, the game time of the answer
    before it and of the answer after it, less the `set_time`'s own, as "before/after".
    """

    label: str
    server: str
    set_times: int
    answers: int
    before: int
    after: int
    around: dict[str, int]


@dataclass(frozen=True, slots=True)
class Plan:
    """What one probe run does: the server, the events or burst queries, the row label."""

    server: str
    events: int
    label: str
    burst: int = 0


def _sent(packet: Packet) -> int:
    """The game time in a `set_time` payload: its first 8 bytes, a Long."""
    return int.from_bytes(packet.payload[:8], "big", signed=True)


async def _start(context: GroupContext, plan: Plan, budget: int) -> tuple[Bot, int]:
    """Join the Bot, freeze, check the `set_time` payload, step `budget`; the start time."""
    bot = await context.bot("lag")
    await bot.join()
    await bot.sync()
    await context.freeze()
    await bot.sync()  # takes any set_time sent before the freeze
    frozen = _sent(await bot.expect(SET_TIME, timeout_s=EVENT_TIMEOUT_S))
    start = gametime(await context.control.run(QUERY))
    print(f"{plan.server}: frozen set_time {frozen}, query {start}", flush=True)
    if frozen != start:
        msg = f"set_time {frozen} is not the game time {start}: the payload is not read"
        raise ValueError(msg)
    await context.control.run(f"tick step {budget}")
    return bot, start


def _events(plan: Plan, rows: list[Row], window: list[int]) -> Group:
    budget = plan.events * TICKS_PER_EVENT + SPARE_TICKS

    async def run(context: GroupContext) -> None:
        bot, start = await _start(context, plan, budget)
        window.extend((start, start + budget))
        while len(rows) < plan.events:
            packet = await bot.expect(SET_TIME, timeout_s=EVENT_TIMEOUT_S)
            arrived = time.monotonic()
            sent = _sent(packet)
            if sent <= start:
                continue
            answer = gametime(await context.control.run(QUERY))
            rows.append(
                Row(
                    label=plan.label,
                    server=plan.server,
                    start=start,
                    budget=budget,
                    sent=sent,
                    answer=answer,
                    added=answer - sent,
                    after_step=answer >= start + budget,
                    wall_ms=round((time.monotonic() - arrived) * 1000, 1),
                    load=os.getloadavg()[0],
                )
            )

    return Group(id="research/time-query-lag", run=run)


def _burst(plan: Plan, window: list[int]) -> Group:
    budget = plan.burst * TICKS_PER_QUERY + SPARE_TICKS

    async def run(context: GroupContext) -> None:
        _, start = await _start(context, plan, budget)
        window.extend((start, start + budget))
        for _ in range(plan.burst):
            # A random pause, so that the answers do not lock on to one phase of the tick.
            await asyncio.sleep(secrets.randbelow(JITTER_MS) / 1000)
            await context.control.run(QUERY)

    return Group(id="research/time-query-lag-burst", run=run)


def _answer(packet: Packet) -> int | None:
    try:
        return gametime((packet,))
    except ValueError:
        return None


def stamps(transcript: Transcript, plan: Plan, window: Sequence[int]) -> Stamps:
    """Read Control's `set_time`s and answers in order, inside the step, and count proofs."""
    start, end = window
    seen: list[tuple[str, int]] = []
    for event in transcript.events:
        packet = event.packet
        if event.bot != CONTROL_PLAYER or packet.direction is not Direction.CLIENTBOUND:
            continue
        if packet.name == SET_TIME:
            seen.append(("set_time", _sent(packet)))
        elif packet.name == SYSTEM_CHAT and (value := _answer(packet)) is not None:
            seen.append(("answer", value))
    inside = [(kind, value) for kind, value in seen if start < value < end]
    pairs = list(itertools.pairwise(inside))
    around = collections.Counter(
        (prev[1] - stamp[1], after[1] - stamp[1])
        for prev, stamp, after in zip(inside, inside[1:], inside[2:], strict=False)
        if stamp[0] == "set_time" and prev[0] == "answer" and after[0] == "answer"
    )
    return Stamps(
        label=plan.label,
        server=plan.server,
        set_times=sum(kind == "set_time" for kind, _ in inside),
        answers=sum(kind == "answer" for kind, _ in inside),
        before=sum(a == ("answer", b[1]) and b[0] == "set_time" for a, b in pairs),
        after=sum(a[0] == "set_time" and b == ("answer", a[1]) for a, b in pairs),
        around={f"{gap[0]:+d}/{gap[1]:+d}": count for gap, count in sorted(around.items())},
    )


async def probe(plan: Plan, workdir: Path) -> list[Row] | Stamps:
    """Boot one Instance of `plan.server` in `workdir`, play the probe once, and stop it."""
    adapter = ADAPTERS[plan.server]()
    installation = install.require(adapter, TARGET, cache_dir())
    endpoint = free_endpoint()
    prepared = adapter.prepare(
        installation, ServerSpec(host=endpoint.host, port=endpoint.port), workdir
    )
    rows: list[Row] = []
    window: list[int] = []
    group = _burst(plan, window) if plan.burst else _events(plan, rows, window)
    async with running(
        prepared,
        ready=status_probe(TARGET),
        ready_timeout=READY_TIMEOUT_S,
        stop_timeout=STOP_TIMEOUT_S,
    ) as instance:
        transcript = await run_group(
            group, instance.endpoint, server=plan.server, timeout_s=GROUP_TIMEOUT_S
        )
    return stamps(transcript, plan, window) if plan.burst else rows


def main(argv: Sequence[str] | None = None) -> int:
    """Run the probe, then print and append each row."""
    parser = argparse.ArgumentParser(prog="time_query_lag.py", description=__doc__)
    parser.add_argument("adapter", choices=sorted(ADAPTERS))
    parser.add_argument("out", type=Path)
    parser.add_argument("--events", type=int, default=60)
    parser.add_argument("--label", default="rest")
    parser.add_argument("--burst", type=int, default=0)
    args = parser.parse_args(argv)
    plan = Plan(args.adapter, args.events, args.label, args.burst)
    workdir = Path(tempfile.mkdtemp(prefix="mscts-research-time-query-lag-"))
    try:
        result = asyncio.run(probe(plan, workdir / "i"))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    rows = result if isinstance(result, list) else [result]
    with args.out.open("a", encoding="utf-8") as sink:
        for row in rows:
            print(row, flush=True)
            sink.write(json.dumps(asdict(row)) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
