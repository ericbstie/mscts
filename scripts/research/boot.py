"""Research only: boot one Adapter's Instance, keep the workdir, print its Endpoint and timing.

Usage: boot.py <adapter> <workdir> [--spec key=value ...] [--keep] [--seconds N]

Gets `adapter`'s Installation via `mscts.install.require` (it never installs one without
a terminal to answer its question on, so a non-interactive run fails naming the install
command), prepares it from a ServerSpec built from the defaults plus any `--spec
key=value` overrides, starts it at a free Endpoint, and prints that Endpoint and how long
it took to become ready. It then waits for Ctrl-C, or `--seconds N`, then stops it.
`--keep` leaves `workdir`; otherwise it is removed afterwards (see the protocol-research
skill's Research harness section for when to read a server's own files, such as
level.dat, from a kept workdir). `workdir` must be new or empty: the Adapter contract
already refuses a non-empty one.
"""

import argparse
import asyncio
import contextlib
import dataclasses
import shutil
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from mscts import install
from mscts.adapters.base import Adapter, Installation
from mscts.bot import status_probe
from mscts.cache import cache_dir
from mscts.cli import ADAPTERS
from mscts.net import Endpoint
from mscts.runner import free_endpoint, running
from mscts.spec import Difficulty, GameMode, ServerSpec, WorldPreset
from mscts.target import TARGET

READY_TIMEOUT_S = 120.0  # a cold vanilla boot unpacks bundled libraries and makes a world
STOP_TIMEOUT_S = 30.0

# ServerSpec fields --spec may not set: they come from the free Endpoint, not an override.
_ENDPOINT_FIELDS = frozenset({"host", "port"})

# How to convert a --spec value into each non-str ServerSpec field's type.
_CONVERTERS: dict[str, Callable[[str], object]] = {
    "max_players": int,
    "view_distance": int,
    "simulation_distance": int,
    "seed": int,
    "compression_threshold": int,
    "world": WorldPreset,
    "game_mode": GameMode,
    "difficulty": Difficulty,
    "operators": lambda value: tuple(name for name in value.split(",") if name),
}


def spec_from_overrides(overrides: Sequence[str], endpoint: Endpoint) -> ServerSpec:
    """The ServerSpec at `endpoint`, with each "key=value" in `overrides` applied.

    Every value is converted to that field's type and passed through ServerSpec's own
    constructor, so an invalid combination (e.g. a host outside loopback) still raises
    from there.

    Raises:
        ValueError: an override is not "key=value", names "host" or "port" (which come
            from `endpoint`), names a field ServerSpec does not have, or its value does
            not convert to that field's type.
    """
    fields = {field.name for field in dataclasses.fields(ServerSpec)} - _ENDPOINT_FIELDS
    values: dict[str, object] = {}
    for override in overrides:
        key, sep, raw = override.partition("=")
        if not sep:
            msg = f"--spec {override!r} is not key=value"
            raise ValueError(msg)
        if key in _ENDPOINT_FIELDS:
            msg = f"--spec {key!r} comes from the Endpoint, not an override"
            raise ValueError(msg)
        if key not in fields:
            msg = f"--spec {key!r} is not a ServerSpec field ({', '.join(sorted(fields))})"
            raise ValueError(msg)
        convert = _CONVERTERS.get(key, str)
        try:
            values[key] = convert(raw)
        except ValueError as error:
            msg = f"--spec {key}={raw!r}: {error}"
            raise ValueError(msg) from error
    spec = ServerSpec(host=endpoint.host, port=endpoint.port)
    return dataclasses.replace(spec, **values) if values else spec


@dataclass(frozen=True, slots=True)
class Prepared:
    """Everything `boot` needs to run one research Instance and clean up after it."""

    adapter: Adapter
    installation: Installation
    spec: ServerSpec
    workdir: Path


async def boot(prepared: Prepared, *, seconds: float | None, keep: bool) -> None:
    """Prepare `prepared.spec` into its workdir, run it, wait, then stop it.

    Waits `seconds` if given, else until cancelled (e.g. by Ctrl-C in `main`). The
    workdir is removed once the Instance has stopped, unless `keep` is True; this runs
    even if the wait is cancelled, so an interrupted boot still cleans up (or keeps) it.
    """
    plan = prepared.adapter.prepare(prepared.installation, prepared.spec, prepared.workdir)
    try:
        async with running(
            plan,
            ready=status_probe(TARGET),
            ready_timeout=READY_TIMEOUT_S,
            stop_timeout=STOP_TIMEOUT_S,
        ) as instance:
            startup_s = (instance.ready_ns - instance.launched_ns) / 1e9
            print(f"{instance.endpoint.host}:{instance.endpoint.port} ready in {startup_s:.2f}s")
            if seconds is not None:
                await asyncio.sleep(seconds)
            else:
                await asyncio.Event().wait()
    finally:
        if not keep:
            shutil.rmtree(prepared.workdir, ignore_errors=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="boot.py", description=__doc__)
    parser.add_argument("adapter", choices=sorted(ADAPTERS))
    parser.add_argument("workdir", type=Path)
    parser.add_argument(
        "--spec",
        action="append",
        default=[],
        metavar="key=value",
        help="override a ServerSpec field (repeatable)",
    )
    parser.add_argument(
        "--keep", action="store_true", help="keep the workdir instead of removing it"
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=None,
        metavar="N",
        help="stop after N seconds instead of waiting for Ctrl-C",
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse `argv` (or sys.argv[1:]); SystemExit(2) on a bad argument."""
    return _parser().parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run boot.py end to end; return its exit code (1: a failure, whose message says why)."""
    args = parse_args(argv)
    adapter = ADAPTERS[args.adapter]()
    terminal = install.Terminal(stdin=sys.stdin, stdout=sys.stdout)
    try:
        installation = install.require(adapter, TARGET, cache_dir(), terminal=terminal)
        spec = spec_from_overrides(args.spec, free_endpoint())
    except (install.ProvisionError, ValueError) as error:
        print(f"boot.py: {error}", file=sys.stderr)
        return 1
    prepared = Prepared(adapter, installation, spec, args.workdir)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(boot(prepared, seconds=args.seconds, keep=args.keep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
