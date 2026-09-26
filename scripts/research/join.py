"""Research only: join a Bot to one Adapter's Instance, and print or save what it saw.

Usage: join.py <adapter> [--spec key=value ...] [--packets name,name,...] [--chunks N]
       [--out file.jsonl]

Boots `adapter`'s Instance (as `boot.py` does: `mscts.install.require`, a ServerSpec from
the defaults plus any `--spec key=value` overrides, a free Endpoint), joins a Bot, then
stops it and removes its scratch workdir. `--packets` prints, in the order they were
seen, every packet named in the comma-separated list: its decoded fields if it has a
schema, else its raw payload as hex. `--chunks N` decodes the first N
`level_chunk_with_light` packets' sections (single-valued and indirect palettes only) and
prints each section's block count and distinct block state and biome ids. `--out` writes
every recorded Event as one JSON object per line (a research format, not a public one).
"""

import argparse
import asyncio
import importlib.util
import json
import shutil
import sys
import tempfile
import types
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path

from mscts import install
from mscts.adapters.base import Adapter, Installation
from mscts.bot import Bot, status_probe
from mscts.cache import cache_dir
from mscts.cli import ADAPTERS
from mscts.codec.packets import Direction, Packet, State
from mscts.runner import free_endpoint, running
from mscts.spec import ServerSpec
from mscts.target import TARGET
from mscts.transcript import Transcript

READY_TIMEOUT_S = 120.0  # a cold vanilla boot unpacks bundled libraries and makes a world
STOP_TIMEOUT_S = 30.0
BOT_TIMEOUT_S = 30.0
BOT_NAME = "research"


def _load_sibling(name: str) -> types.ModuleType:
    """Import `name`.py next to this script, however this script itself was loaded."""
    path = Path(__file__).resolve().with_name(f"{name}.py")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# `spec_from_overrides` (the --spec parsing boot.py already has) and the chunk decoder,
# loaded by path so neither script depends on the other being importable as a package.
boot = _load_sibling("boot")
chunkformat = _load_sibling("chunkformat")


async def join(
    adapter: Adapter, installation: Installation, spec: ServerSpec, workdir: Path
) -> Transcript:
    """Boot `adapter`'s Instance at `spec` in `workdir`, join a Bot, then stop it.

    Returns the Transcript once the Bot has joined (its first chunk batch finished).
    `workdir` is removed once the Instance has stopped, whatever happened.
    """
    plan = adapter.prepare(installation, spec, workdir)
    transcript = Transcript(scenario_id="research/join", server=adapter.name)
    try:
        async with running(
            plan,
            ready=status_probe(TARGET),
            ready_timeout=READY_TIMEOUT_S,
            stop_timeout=STOP_TIMEOUT_S,
        ) as instance:
            bot = await Bot.connect(
                instance.endpoint,
                TARGET,
                name=BOT_NAME,
                transcript=transcript,
                timeout_s=BOT_TIMEOUT_S,
            )
            try:
                await bot.join()
            finally:
                await bot.close()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return transcript


def _print_packet(packet: Packet) -> None:
    if packet.fields is not None:
        print(packet.name, dict(packet.fields))
    else:
        print(packet.name, packet.payload.hex())


def _print_chunks(transcript: Transcript, count: int) -> None:
    payloads = [
        event.packet.payload
        for event in transcript.events
        if (event.packet.state, event.packet.direction, event.packet.name)
        == (State.PLAY, Direction.CLIENTBOUND, "minecraft:level_chunk_with_light")
    ][:count]
    for payload in payloads:
        chunk = chunkformat.decode_chunk(payload, chunkformat.OVERWORLD_SECTIONS)
        print(f"chunk ({chunk.x}, {chunk.z}): {len(chunk.sections)} sections")
        for index, section in enumerate(chunk.sections):
            states = sorted(set(section.states))
            biomes = sorted(set(section.biomes))
            print(
                f"  section {index}: block_count={section.block_count} "
                f"states={states} biomes={biomes}"
            )


def report(transcript: Transcript, packet_names: frozenset[str], chunk_count: int) -> None:
    """Print every recorded packet named in `packet_names`, then `chunk_count` chunks."""
    for event in transcript.events:
        if event.packet.name in packet_names:
            _print_packet(event.packet)
    if chunk_count:
        _print_chunks(transcript, chunk_count)


def jsonable(value: object) -> object:
    """`value` (a decoded field's value) as something `json.dumps` accepts."""
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(item) for item in value]
    return value


def write_jsonl(transcript: Transcript, path: Path) -> None:
    """Write every recorded Event as one JSON object per line, in `transcript`'s order."""
    with path.open("w", encoding="utf-8") as file:
        for event in transcript.events:
            packet = event.packet
            row = {
                "t_ns": event.t_ns,
                "bot": event.bot,
                "state": packet.state.value,
                "direction": packet.direction.value,
                "name": packet.name,
                "packet_id": packet.packet_id,
                "payload_hex": packet.payload.hex(),
                "fields": jsonable(packet.fields) if packet.fields is not None else None,
            }
            file.write(json.dumps(row) + "\n")


def packet_names(raw: str) -> frozenset[str]:
    """The non-empty names in `raw`, a comma-separated `--packets` value."""
    return frozenset(name for name in raw.split(",") if name)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="join.py", description=__doc__)
    parser.add_argument("adapter", choices=sorted(ADAPTERS))
    parser.add_argument(
        "--spec",
        action="append",
        default=[],
        metavar="key=value",
        help="override a ServerSpec field (repeatable)",
    )
    parser.add_argument(
        "--packets",
        default="",
        metavar="name,name,...",
        help="packet names to print, decoded (or hex if they have no schema)",
    )
    parser.add_argument(
        "--chunks",
        type=int,
        default=0,
        metavar="N",
        help="decode the first N level_chunk_with_light packets' sections",
    )
    parser.add_argument(
        "--out", type=Path, default=None, metavar="file.jsonl", help="write the Transcript as JSONL"
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse `argv` (or sys.argv[1:]); SystemExit(2) on a bad argument."""
    return _parser().parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run join.py end to end; return its exit code (1: a failure, whose message says why)."""
    args = parse_args(argv)
    adapter = ADAPTERS[args.adapter]()
    terminal = install.Terminal(stdin=sys.stdin, stdout=sys.stdout)
    try:
        installation = install.require(adapter, TARGET, cache_dir(), terminal=terminal)
        spec = boot.spec_from_overrides(args.spec, free_endpoint())
    except (install.ProvisionError, ValueError) as error:
        print(f"join.py: {error}", file=sys.stderr)
        return 1
    workdir = Path(tempfile.mkdtemp(prefix="mscts-research-join-"))
    transcript = asyncio.run(join(adapter, installation, spec, workdir))
    report(transcript, packet_names(args.packets), args.chunks)
    if args.out is not None:
        write_jsonl(transcript, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
