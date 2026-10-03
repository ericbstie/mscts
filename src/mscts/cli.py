"""The `mscts` command (ADR-0008): every command says what it did, and every error its fix."""

import argparse
import asyncio
import contextlib
import fnmatch
import functools
import logging
import os
import shutil
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from time import perf_counter
from types import MappingProxyType
from typing import override

from mscts import install, registry, report_json, run
from mscts.adapters.base import Adapter, Installation, PrepareError, ProvisionError
from mscts.adapters.fetch import Download, Fetch, https_get
from mscts.adapters.pumpkin import PumpkinAdapter
from mscts.adapters.vanilla import VanillaAdapter
from mscts.cache import cache_dir
from mscts.group import GROUPS, Group, GroupKind, resolve
from mscts.registry import RegistryError
from mscts.report import Report, render_markdown, render_text
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


class _OutputError(Exception):
    """A finished Run's Report that could not be written to a file; the message names it."""


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
    out = None if arguments.out is None else _made_out_folder(Path(arguments.out))
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
    if out is not None:
        _say(_write_report(report, out, verbose=arguments.verbose))
    return 0


def _made_out_folder(folder: Path) -> Path:
    """`folder`, made if it is not there yet: before the Run, so a bad --out costs no Run."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        msg = f"cannot create the --out folder {folder}: {error.strerror}"
        raise _UsageError(msg) from error
    return folder


def _write_report(report: Report, folder: Path, *, verbose: bool) -> str:
    """Write report.json and report.md into `folder`, replacing any; say where they are.

    Both are written to temporary files first, and replace the earlier pair only once
    both are written, so a file that cannot be made leaves the earlier pair as it was.
    """
    files: dict[Path, Callable[[], str]] = {
        folder / "report.json": lambda: report_json.dumps(report),
        folder / "report.md": lambda: render_markdown(report, verbose=verbose),
    }
    staged: dict[Path, Path] = {}
    try:
        for path, render in files.items():
            staged[path] = _staged(path, render)
        for path, temporary in staged.items():
            _failing_as_unwritable(path, functools.partial(temporary.replace, path))
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)
    return f"Report written to {' and '.join(map(str, files))}"


def _staged(path: Path, render: Callable[[], str]) -> Path:
    """A temporary file beside `path` holding `render()`'s text, for `path` to replace."""
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        _failing_as_unwritable(path, lambda: temporary.write_text(render(), encoding="utf-8"))
    except BaseException:
        temporary.unlink()
        raise
    return temporary


def _failing_as_unwritable(path: Path, write: Callable[[], object]) -> None:
    """Do `write`; a failure to make, encode or write `path` says so, naming it."""
    try:
        write()
    except (OSError, TypeError, ValueError) as error:
        msg = f"cannot write {path}: {_reason(error)}"
        raise _OutputError(msg) from error


def _reason(error: Exception) -> str:
    """Why writing a file failed: the system's words, or the error's own."""
    return error.strerror if isinstance(error, OSError) and error.strerror else str(error)


_ACTIONS: Mapping[str, Callable[[argparse.Namespace, Fetch], int]] = MappingProxyType(
    {"install": _install, "list": _list, "status": _status, "run": _run}
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
    running.add_argument(
        "--out",
        metavar="DIR",
        help="also write the Report to DIR/report.json and DIR/report.md, replacing them",
    )
    return parser


def main(argv: Sequence[str] | None = None, *, fetch: Fetch = https_get) -> int:
    """Run the `mscts` command; return its exit code (1: a failure, whose message says why)."""
    arguments = _parser().parse_args(argv)
    said = _SayingHandler()
    install.LOG.addHandler(said)  # what an install did on its own, e.g. recording SOURCE.json
    try:
        command = str(arguments.command)
        action = str(arguments.action) if command == "adapter" else command
        return _ACTIONS[action](arguments, fetch)
    except (ProvisionError, RegistryError, PrepareError, _UsageError, _OutputError) as error:
        sys.stderr.write(f"mscts: {error}\n")
        return 1
    finally:
        install.LOG.removeHandler(said)
