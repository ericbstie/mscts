"""The `mscts` command (ADR-0008): every command says what it did, and every error its fix."""

import argparse
import asyncio
import contextlib
import fnmatch
import logging
import shutil
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from time import perf_counter
from types import MappingProxyType
from typing import override

from mscts import install, run
from mscts.adapters.base import (
    Adapter,
    Download,
    Fetch,
    Installation,
    PrepareError,
    ProvisionError,
)
from mscts.adapters.fetch import https_get
from mscts.adapters.pumpkin import PumpkinAdapter
from mscts.adapters.vanilla import VanillaAdapter
from mscts.cache import cache_dir
from mscts.group import GROUPS, Group, GroupKind, resolve
from mscts.report import Report, render_text
from mscts.runner import RunnerError
from mscts.target import TARGET

# Every Adapter the command knows, by name.
ADAPTERS: Mapping[str, Callable[[], Adapter]] = MappingProxyType(
    {"vanilla": VanillaAdapter, "pumpkin": PumpkinAdapter}
)


REFERENCE = "vanilla"
"""The Reference's Adapter: every Run compares a Candidate with it."""

DEFAULT_GROUPS = "status/*"
"""The Groups `mscts run` plays unless `--group` says otherwise."""

DEFAULT_REPEAT = 5
"""How many times `mscts run` plays each Group unless `--repeat` says otherwise."""


class _UsageError(Exception):
    """A command line the command cannot act on; its message names the fix."""


def _say(text: str) -> None:
    sys.stdout.write(text + "\n")


class _ProgressHandler(logging.Handler):
    """Shows each record on stderr: progress, kept apart from the Report on stdout."""

    @override
    def emit(self, record: logging.LogRecord) -> None:
        sys.stderr.write(record.getMessage() + "\n")
        sys.stderr.flush()


@contextlib.contextmanager
def _progress() -> Iterator[None]:
    """Show what the Run does (its INFO records) on stderr while the block runs."""
    handler = _ProgressHandler()
    level = run.LOG.level
    run.LOG.addHandler(handler)
    run.LOG.setLevel(logging.INFO)
    try:
        yield
    finally:
        run.LOG.removeHandler(handler)
        run.LOG.setLevel(level)


def _saying(fetch: Fetch) -> Fetch:
    """`fetch`, announcing each download first: nothing downloads without saying so."""

    def announced(url: str) -> Download:
        _say(f"downloading {url} ...")
        return fetch(url)

    return announced


def _adapter_at(argument: str) -> tuple[str, str | None]:
    """`<adapter>` or `<adapter>@<version>`, split; a usage error unless the Adapter is known."""
    name, at, version = argument.partition("@")
    if name not in ADAPTERS:
        msg = f"{name!r} is no Adapter; the known Adapters are {', '.join(ADAPTERS)}"
        raise argparse.ArgumentTypeError(msg)
    if at and not version:
        msg = f"{argument} names no version: name one after the @, or leave the @ out"
        raise argparse.ArgumentTypeError(msg)
    return name, version or None


def _install(arguments: argparse.Namespace, fetch: Fetch) -> int:
    name, version = arguments.adapter
    adapter = ADAPTERS[name]()
    if arguments.from_path is not None:
        if version is not None:
            msg = (
                f"{name}@{version} --from {arguments.from_path}: name a version or a file, not both"
            )
            raise _UsageError(msg)
        done = install.install_from(adapter, TARGET, cache_dir(), Path(arguments.from_path))
    else:
        done = install.install_release(adapter, TARGET, cache_dir(), version, _saying(fetch))
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
        build = installation.source.build if installation and installation.source else None
        if broken is not None:
            state = f"unusable: see `mscts adapter status {name}`"
        else:
            state = "not installed" if installation is None else "installed"
        rows.append((name, str(build or "-"), TARGET.minecraft_version, state))
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
        fields = (
            ("version", source.version or "unknown"),
            ("commit", source.commit),
            ("sha256", source.sha256),
            ("size", f"{source.size} bytes"),
            ("from", source.from_path or source.url or "unknown"),
            ("installed", source.installed_at or "unknown"),
        )
        for label, value in fields:
            if value is not None:
                _say(f"  {label + ':':<11}{value}")
    return 0


def _groups(pattern: str) -> tuple[Group, ...]:
    """The registered exact Groups whose id matches `pattern`, with their prerequisites."""
    exact = sorted(group_id for group_id, group in GROUPS.items() if group.kind is GroupKind.EXACT)
    chosen = [group_id for group_id in exact if fnmatch.fnmatchcase(group_id, pattern)]
    if not chosen:
        msg = (
            f"no registered exact Group matches --group {pattern!r}; "
            f"the registered ones are {', '.join(exact)}"
        )
        raise _UsageError(msg)
    return resolve(chosen)


def _server(name: str) -> run.Server:
    adapter = ADAPTERS[name]()
    terminal = install.Terminal(sys.stdin, sys.stdout)
    return run.Server(adapter, install.require(adapter, TARGET, cache_dir(), terminal=terminal))


def _run(arguments: argparse.Namespace, _fetch: Fetch) -> int:
    groups = _groups(str(arguments.group))
    repeat = int(arguments.repeat)
    if repeat < 1:
        msg = f"--repeat must be at least 1, not {repeat}"
        raise _UsageError(msg)
    reference, candidate = _server(REFERENCE), _server(str(arguments.candidate))
    started = perf_counter()
    workdir = Path(tempfile.mkdtemp(prefix="mscts-run-"))
    try:
        with _progress():
            result = asyncio.run(
                run.run_results(groups, reference, candidate, workdir=workdir, repeat=repeat)
            )
    except RunnerError as error:  # the workdir stays: its console log is the evidence
        msg = f"{error.reason}; its console log is kept at {error.log_path}"
        raise _UsageError(msg) from error
    except BaseException:
        shutil.rmtree(workdir)
        raise
    shutil.rmtree(workdir)
    report = Report.of(result, target=TARGET, notes=(), elapsed_s=perf_counter() - started)
    sys.stdout.write(render_text(report, verbose=arguments.verbose))
    return 0


_ACTIONS: Mapping[str, Callable[[argparse.Namespace, Fetch], int]] = MappingProxyType(
    {"install": _install, "list": _list, "status": _status, "run": _run}
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mscts", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    adapter = commands.add_parser("adapter", help="install and inspect server Installations")
    actions = adapter.add_subparsers(dest="action", required=True)
    installing = actions.add_parser(
        "install", help="install the latest build, the build @VERSION names, or --from a file"
    )
    installing.add_argument(
        "adapter",
        type=_adapter_at,
        metavar="ADAPTER[@VERSION]",
        help=f"{' or '.join(ADAPTERS)}; @VERSION installs one build, not the latest",
    )
    installing.add_argument("--from", dest="from_path", metavar="PATH", help="a binary you supply")
    actions.add_parser("list", help="Adapters, and what is installed")
    status = actions.add_parser("status", help="what is installed, its sha256 and its source")
    status.add_argument("adapter", choices=ADAPTERS, help="the Adapter whose Installation to show")
    running = commands.add_parser(
        "run", help="play Groups against vanilla and a Candidate, and print the Report"
    )
    running.add_argument(
        "--candidate", required=True, choices=ADAPTERS, help="the Candidate's Adapter"
    )
    running.add_argument(
        "--group",
        default=DEFAULT_GROUPS,
        metavar="GLOB",
        help=f"the Group ids to play, prerequisites added (default: {DEFAULT_GROUPS})",
    )
    running.add_argument(
        "--repeat",
        type=int,
        default=DEFAULT_REPEAT,
        metavar="N",
        help=f"how many times to play each Group (default: {DEFAULT_REPEAT})",
    )
    running.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="show installed versions, values and Group times",
    )
    return parser


def main(argv: Sequence[str] | None = None, *, fetch: Fetch = https_get) -> int:
    """Run the `mscts` command; return its exit code (1: a failure, whose message says why)."""
    arguments = _parser().parse_args(argv)
    try:
        command = str(arguments.command)
        action = str(arguments.action) if command == "adapter" else command
        return _ACTIONS[action](arguments, fetch)
    except (ProvisionError, PrepareError, _UsageError) as error:
        sys.stderr.write(f"mscts: {error}\n")
        return 1
