"""Research only: play `player/respawn` and `player/fire` on vanilla, clear and in a storm.

Usage: weather_probe.py [PLAYS]

Made for #426. Boots one vanilla Instance at the Groups' ServerSpec (normal difficulty), and
plays each Group PLAYS times (default 1) as it is, then sets `weather thunder` through a
Control of its own, lets the world run for `STORM_S` so that the rain and thunder levels reach
1, and plays each Group PLAYS times again. The storm plays come last, so a storm cannot reach
a clear play.

Each play prints one JSON line: the Group, the weather it was set in, the error the Group
raised (a `GroupError`'s description, or null), and for each Observation window the weather
`game_event`s (events 1, 2, 7 and 8) its Bots received in it, as `[bot, event, value]`.
A last line counts, for each Group and weather, the plays that raised and the plays whose
windows held a weather `game_event`.
"""

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import mscts.groups  # noqa: F401 - registers the shipped Groups
from mscts import install
from mscts.adapters.vanilla import VanillaAdapter
from mscts.bot import status_probe
from mscts.cache import cache_dir
from mscts.codec.packets import Direction
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN
from mscts.group import GROUPS, GroupContext
from mscts.net import Endpoint
from mscts.run import GroupError, run_group
from mscts.runner import free_endpoint, running
from mscts.spec import CONTROL_PLAYER, ServerSpec
from mscts.target import TARGET
from mscts.transcript import Transcript

READY_TIMEOUT_S = 120.0
STOP_TIMEOUT_S = 30.0
CONTROL_TIMEOUT_S = 30.0
STORM_S = 8.0
"""How long the world runs after `weather thunder`: the levels rise 0.01 a tick, 100 ticks."""
GROUP_IDS = ("player/respawn", "player/fire")
GAME_EVENT = "minecraft:game_event"
WEATHER_EVENTS = frozenset({1, 2, 7, 8})
"""START_RAINING, STOP_RAINING, RAIN_LEVEL_CHANGE and THUNDER_LEVEL_CHANGE."""


def windows(transcript: Transcript) -> list[tuple[int, int]]:
    """The `(open, close)` times of each Observation window in `transcript`."""
    opens = [mark.t_ns for mark in transcript.marks if mark.label.startswith(OBSERVE_OPEN)]
    closes = [mark.t_ns for mark in transcript.marks if mark.label == OBSERVE_CLOSE]
    return list(zip(opens, closes, strict=False))


def weather_in(transcript: Transcript, window: tuple[int, int]) -> list[list[object]]:
    """The weather `game_event`s each Bot but Control received inside `window`."""
    opened, closed = window
    seen: list[list[object]] = []
    for event in transcript.events:
        packet = event.packet
        fields = packet.fields or {}
        if (
            packet.name == GAME_EVENT
            and packet.direction is Direction.CLIENTBOUND
            and event.bot != CONTROL_PLAYER
            and opened <= event.t_ns <= closed
            and fields.get("event") in WEATHER_EVENTS
        ):
            seen.append([event.bot, fields.get("event"), fields.get("value")])
    return seen


async def storm(endpoint: Endpoint) -> None:
    """Set `weather thunder` through a Control of its own, and let the world run `STORM_S`."""
    transcript = Transcript(group_id="research/storm", server="vanilla")
    context = GroupContext(endpoint, transcript, timeout_s=CONTROL_TIMEOUT_S)
    try:
        await context.control.run("weather thunder")
    finally:
        await context.close()
    await asyncio.sleep(STORM_S)


@dataclass(frozen=True, slots=True)
class Play:
    """One play: its Group, the weather it was set in, its error, and each window's weather."""

    group: str
    weather: str
    error: str | None
    windows: list[list[list[object]]]


async def one_play(endpoint: Endpoint, group_id: str, weather: str) -> Play:
    """Play `group_id` once, and return what its windows saw of the weather."""
    error = None
    try:
        transcript = await run_group(GROUPS[group_id], endpoint, server="vanilla")
    except GroupError as exc:
        transcript, error = exc.transcript, str(exc)
    seen = [weather_in(transcript, window) for window in windows(transcript)]
    return Play(group_id, weather, error, seen)


async def probe(plays: int, workdir: Path) -> Counter[str]:
    """Boot one vanilla Instance, play the Groups clear then in a storm, and count the plays."""
    adapter = VanillaAdapter()
    installation = install.require(adapter, TARGET, cache_dir())
    endpoint = free_endpoint()
    spec = GROUPS[GROUP_IDS[0]].spec(ServerSpec(host=endpoint.host, port=endpoint.port))
    plan = adapter.prepare(installation, spec, workdir)
    counts: Counter[str] = Counter()
    async with running(
        plan, ready=status_probe(TARGET), ready_timeout=READY_TIMEOUT_S, stop_timeout=STOP_TIMEOUT_S
    ) as instance:
        for weather in ("clear", "thunder"):
            if weather == "thunder":
                await storm(instance.endpoint)
            for group_id in GROUP_IDS:
                for _ in range(plays):
                    play = await one_play(instance.endpoint, group_id, weather)
                    print(json.dumps(asdict(play)), flush=True)
                    counts[f"{group_id} {weather} plays"] += 1
                    counts[f"{group_id} {weather} raised"] += play.error is not None
                    counts[f"{group_id} {weather} weather events"] += any(play.windows)
    return counts


def main(argv: Sequence[str] | None = None) -> int:
    """Run the probe, then print the counts."""
    parser = argparse.ArgumentParser(prog="weather_probe.py", description=__doc__)
    parser.add_argument("plays", type=int, nargs="?", default=1)
    args = parser.parse_args(argv)
    workdir = Path(tempfile.mkdtemp(prefix="mscts-research-weather-"))
    try:
        counts = asyncio.run(probe(args.plays, workdir / "vanilla"))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    print(json.dumps(dict(sorted(counts.items()))), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
