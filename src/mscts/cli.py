"""The `mscts` command (ADR-0008): every command says what it did, and every error its fix."""

import argparse
import logging
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import override

from mscts import install, registry
from mscts.adapters.base import Adapter, Installation, ProvisionError
from mscts.adapters.fetch import Download, Fetch, https_get
from mscts.adapters.pumpkin import PumpkinAdapter
from mscts.adapters.vanilla import VanillaAdapter
from mscts.cache import cache_dir
from mscts.registry import RegistryError
from mscts.target import TARGET

# Every Adapter the command knows, by name.
ADAPTERS: Mapping[str, Callable[[], Adapter]] = MappingProxyType(
    {"vanilla": VanillaAdapter, "pumpkin": PumpkinAdapter}
)


def _say(text: str) -> None:
    sys.stdout.write(text + "\n")


class _SayingHandler(logging.Handler):
    """Says each record, as the command's own output."""

    @override
    def emit(self, record: logging.LogRecord) -> None:
        _say(record.getMessage())


def _saying(fetch: Fetch) -> Fetch:
    """`fetch`, announcing each download first: nothing downloads without saying so."""

    def announced(url: str) -> Download:
        _say(f"downloading {url} ...")
        return fetch(url)

    return announced


def _install(arguments: argparse.Namespace, fetch: Fetch) -> int:
    adapter = ADAPTERS[arguments.adapter]()
    if arguments.from_path is not None:
        done = install.install_from(
            adapter, TARGET, cache_dir(), Path(arguments.from_path), registry.official()
        )
    else:
        entry = registry.official().resolve(adapter.name, TARGET, arguments.version)
        done = install.install_entry(adapter, TARGET, cache_dir(), entry, _saying(fetch))
    _say(done.message)
    return 0


def _state(adapter: Adapter) -> tuple[Installation | None, str | None]:
    """The adapter's verified Installation, or why it cannot be used."""
    try:
        return install.installed(adapter, TARGET, cache_dir()), None
    except ProvisionError as error:
        return None, str(error)


def _list(_arguments: argparse.Namespace, _fetch: Fetch) -> int:
    rows = [("ADAPTER", "VERSION", "TARGET", "STATE")]
    for name, make in ADAPTERS.items():
        installation, broken = _state(make())
        source = installation.source if installation else None
        entries = [entry for entry in registry.official().entries if entry.adapter == name]
        for entry in entries:
            state = "installed" if source and source.entry == str(entry) else "not installed"
            rows.append((name, entry.version, entry.target, state))
        if source is not None and source.entry is None:
            rows.append(
                (name, "-", TARGET.minecraft_version, "installed: " + install.describe(source))
            )
        if broken is not None:
            rows.append(
                (
                    name,
                    "-",
                    TARGET.minecraft_version,
                    f"unusable: see `mscts adapter status {name}`",
                )
            )
        if not entries and installation is None and broken is None:
            rows.append((name, "-", "-", "no Registry entry; install one with --from"))
    widths = [max(len(row[column]) for row in rows) for column in range(3)]
    for row in rows:
        padded = [cell.ljust(width) for cell, width in zip(row, widths, strict=False)]
        _say("  ".join([*padded, row[3]]))
    return 0


def _status(arguments: argparse.Namespace, _fetch: Fetch) -> int:
    adapter = ADAPTERS[arguments.adapter]()
    what = f"{adapter.name} {TARGET.minecraft_version}"
    installation = install.installed(adapter, TARGET, cache_dir())
    if installation is None:
        _say(f"{what}: not installed. Install it with `{install.install_command(adapter.name)}`")
        return 1
    _say(f"{what}: installed at {installation.root}")
    source = installation.source
    if source is not None:
        origin = source.from_path or source.url or "found in the cache, matched by hash"
        fields = (
            ("entry", source.entry or "none (this build hash-matches no Registry entry)"),
            ("sha256", source.sha256),
            ("size", f"{source.size} bytes"),
            ("from", origin),
            ("installed", source.installed_at or "unknown"),
        )
        for label, value in fields:
            _say(f"  {label + ':':<11}{value}")
    return 0


_ACTIONS: Mapping[str, Callable[[argparse.Namespace, Fetch], int]] = MappingProxyType(
    {"install": _install, "list": _list, "status": _status}
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mscts", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    adapter = commands.add_parser("adapter", help="install and inspect server Installations")
    actions = adapter.add_subparsers(dest="action", required=True)
    installing = actions.add_parser("install", help="install a Registry entry, or --from a file")
    installing.add_argument("adapter", choices=ADAPTERS)
    source = installing.add_mutually_exclusive_group()
    source.add_argument("--version", help="the Registry entry's version (default: the Target's)")
    source.add_argument("--from", dest="from_path", metavar="PATH", help="a binary you supply")
    actions.add_parser("list", help="Adapters, Registry entries, and what is installed")
    status = actions.add_parser("status", help="what is installed, its sha256 and its source")
    status.add_argument("adapter", choices=ADAPTERS)
    return parser


def main(argv: Sequence[str] | None = None, *, fetch: Fetch = https_get) -> int:
    """Run the `mscts` command; return its exit code (1: a failure, whose message says why)."""
    arguments = _parser().parse_args(argv)
    said = _SayingHandler()
    install.LOG.addHandler(said)  # what an install did on its own, e.g. recording SOURCE.json
    try:
        return _ACTIONS[str(arguments.action)](arguments, fetch)
    except (ProvisionError, RegistryError) as error:
        sys.stderr.write(f"mscts: {error}\n")
        return 1
    finally:
        install.LOG.removeHandler(said)
