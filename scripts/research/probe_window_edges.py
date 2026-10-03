"""Research only: play a Group as a Self-check and record what crosses each window's edges.

Usage: probe_window_edges.py PLAYS OUT.jsonl [--group blocks/fill] [--bot builder]

Plays the Group PLAYS times, Reference against Reference, on Instances of its own, as
`mscts run` would, and appends one JSON line per play to OUT.jsonl: the Verdict, the load
average, and for each window of each side, as the Bot named with `--bot` sees it:

- `leaked`: compared packets inside the window that arrived before the Bot sent its first
  `chat_command` in it, so that command cannot have caused them;
- `late`: compared packets that arrived after the Bot's close Mark and before Control's
  next `chat_command` (the next case's setup);
- `margin_ms`: the open Mark minus the arrival of the last compared packet before it.

"Compared" means the play packets the window is narrowed to. Made for #129: run it under
`scripts/repeat.py --stress`'s load, or beside a looping `mise run check`. Times are in
milliseconds. It prints the totals, and exits 0 whatever it found.
"""

import argparse
import asyncio
import json
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

import mscts.run as run_module
from mscts import install
from mscts.adapters.vanilla import VanillaAdapter
from mscts.cache import cache_dir
from mscts.codec.packets import Direction, State
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN, Outcome, Verdict
from mscts.group import Group, resolve
from mscts.run import GroupError, Server
from mscts.spec import CONTROL_PLAYER
from mscts.target import TARGET
from mscts.transcript import Event, Transcript

COMMAND = "minecraft:chat_command"


def _ms(t_ns: int) -> float:
    return round(t_ns / 1e6, 3)


def _name(event: Event) -> str:
    return event.packet.name.removeprefix("minecraft:")


def _commands(transcript: Transcript, bot: str) -> list[int]:
    """When `bot` sent each `chat_command`."""
    return [
        event.t_ns
        for event in transcript.events
        if event.bot == bot
        and event.packet.direction is Direction.SERVERBOUND
        and event.packet.name == COMMAND
    ]


def windows(transcript: Transcript, bot: str) -> list[dict[str, object]]:
    """Each window of `transcript` as `bot` sees it: what crossed its edges."""
    marks = sorted(transcript.marks, key=lambda mark: mark.t_ns)
    opens = [mark for mark in marks if mark.label.split()[0] == OBSERVE_OPEN]
    closes = [m.t_ns for m in marks if m.label in (OBSERVE_CLOSE, f"{OBSERVE_CLOSE} {bot}")]
    own, setup = _commands(transcript, bot), _commands(transcript, CONTROL_PLAYER)
    out: list[dict[str, object]] = []
    for opened in opens:
        narrowed = set(opened.label.split()[1:])
        compared = [
            event
            for event in transcript.events
            if event.bot == bot
            and event.packet.direction is Direction.CLIENTBOUND
            and event.packet.state is State.PLAY
            and (not narrowed or event.packet.name in narrowed)
        ]
        closed = next((t for t in closes if t > opened.t_ns), None)
        command = next((t for t in own if t >= opened.t_ns), None)
        before = [event for event in compared if event.t_ns < opened.t_ns]
        leaked = [
            [_name(event), _ms(event.t_ns - opened.t_ns)]
            for event in compared
            if command is not None and opened.t_ns <= event.t_ns < command
        ]
        late: list[list[object]] = []
        if closed is not None:
            next_setup = next((t for t in setup if t > closed), None)
            late = [
                [_name(event), _ms(event.t_ns - closed)]
                for event in compared
                if event.t_ns >= closed and (next_setup is None or event.t_ns < next_setup)
            ]
        out.append(
            {
                "margin_ms": _ms(opened.t_ns - before[-1].t_ns) if before else None,
                "leaked": leaked,
                "late": late,
            }
        )
    return out


def _transcript(side: Transcript | GroupError) -> Transcript:
    return side.transcript if isinstance(side, GroupError) else side


async def probe(played: Group, plays: int, out: Path, bot: str) -> dict[str, int]:
    """Play `played` `plays` times as a Self-check; append a line per play to `out`."""
    counts = {"match": 0, "other": 0, "leaked": 0, "late": 0}
    original = run_module.judge

    def judge(
        group: Group, reference: Transcript | GroupError, candidate: Transcript | GroupError
    ) -> Verdict:
        verdict = original(group, reference, candidate)
        counts["match" if verdict.outcome is Outcome.MATCH else "other"] += 1
        record: dict[str, object] = {
            "t": time.time(),
            "outcome": verdict.outcome.value,
            "load": Path("/proc/loadavg").read_text().split()[:3],
        }
        if verdict.outcome is not Outcome.MATCH:
            record["divergences"] = [
                {"kind": d.kind, "bot": d.bot, "packet": d.packet, "path": d.path}
                for d in verdict.divergences
            ]
        for name, side in (("reference", reference), ("candidate", candidate)):
            edges = windows(_transcript(side), bot)
            counts["leaked"] += sum(bool(window["leaked"]) for window in edges)
            counts["late"] += sum(bool(window["late"]) for window in edges)
            record[name] = edges
        with out.open("a") as handle:
            handle.write(json.dumps(record) + "\n")
        return verdict

    adapter = VanillaAdapter()
    server = Server(adapter, install.require(adapter, TARGET, cache_dir()))
    # A research patch: ty types a module function as its own literal, so no other fits.
    run_module.judge = judge  # ty: ignore[invalid-assignment]
    try:
        with tempfile.TemporaryDirectory() as workdir:
            await run_module.run([played], server, server, workdir=Path(workdir), repeat=plays)
    finally:
        run_module.judge = original
    return counts


def main(argv: Sequence[str] | None = None) -> None:
    """Parse the command line, probe, and print the totals."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("plays", type=int)
    parser.add_argument("out", type=Path)
    parser.add_argument("--group", default="blocks/fill")
    parser.add_argument("--bot", default="builder")
    args = parser.parse_args(argv)
    (group,) = resolve([args.group])
    print(asyncio.run(probe(group, args.plays, args.out, args.bot)))


if __name__ == "__main__":
    main()
