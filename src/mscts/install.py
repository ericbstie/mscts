"""Installations (ADR-0008): explicit, idempotent, and honest about where a binary came from.

An Installation is `<cache>/<adapter>/<Minecraft version>/`: the Adapter's one binary and
SOURCE.json, which records its sha256 and its source (a Registry entry, or a `--from`
file). It is written in one rename, complete or not at all, and never refreshed: to
change it, delete it and install again.
"""

import dataclasses
import datetime
import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from mscts import registry
from mscts.adapters.base import Adapter, Installation, ProvisionError, Source
from mscts.adapters.fetch import Download, Fetch, https_get
from mscts.registry import Entry, Registry, RegistryError
from mscts.target import Target

SOURCE = "SOURCE.json"


@dataclass(frozen=True, slots=True)
class Installed:
    """What an install did: the Installation, and one sentence saying so."""

    installation: Installation
    changed: bool  # False: it was installed and verified already, so nothing was done
    message: str


def root_of(adapter: Adapter, target: Target, cache_dir: Path) -> Path:
    """Where `adapter`'s Installation for `target` lives in `cache_dir`."""
    return cache_dir.absolute() / adapter.name / target.minecraft_version


def install_command(adapter: str, *, version: str | None = None, path: str | None = None) -> str:
    """The exact `mscts adapter install` command line for an entry or a `--from` file."""
    if path is not None:
        return f"mscts adapter install {adapter} --from {path}"
    return f"mscts adapter install {adapter}" + (f" --version {version}" if version else "")


def _reinstall(adapter: Adapter, root: Path) -> str:
    return f"delete {root} and run `{install_command(adapter.name)}` again"


def describe(source: Source) -> str:
    """Where an Installation came from, in words: its entry, its `--from` file, or neither."""
    origin = source.entry or "no Registry entry"
    if source.from_path is not None:
        return f"{origin}, from {source.from_path} (sha256 {source.sha256})"
    if source.url is not None:
        return f"{origin}, from {source.url} (sha256 {source.sha256})"
    return f"{origin}, found in the cache and matched by hash (sha256 {source.sha256})"


def _record_unrecorded(root: Path, adapter: Adapter, target: Target) -> None:
    """Write SOURCE.json for an Installation made before sources were recorded.

    Only when its binary hash-matches a Registry entry, which is then all it records: it
    claims no URL or file it cannot prove. Anything else stays unrecorded (and refused).
    """
    binary = root / adapter.binary
    if (root / SOURCE).exists() or not binary.is_file():
        return
    body = binary.read_bytes()
    for entry in registry.official().entries:
        if (entry.adapter, entry.target) == (adapter.name, target.minecraft_version) and (
            entry.matches(body)
        ):
            source = Source(
                sha256=hashlib.sha256(body).hexdigest(), size=len(body), entry=str(entry)
            )
            descriptor, part = tempfile.mkstemp(dir=root, prefix=f".{SOURCE}.", suffix=".part")
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                file.write(json.dumps(dataclasses.asdict(source), indent=2) + "\n")
            Path(part).replace(root / SOURCE)
            return


def _read_source(root: Path, adapter: Adapter) -> Source:
    """The Source recorded in `root`/SOURCE.json."""
    try:
        recorded: object = json.loads((root / SOURCE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        msg = f"{root} is not a recorded Installation ({error}); {_reinstall(adapter, root)}"
        raise ProvisionError(msg) from error
    fields = recorded if isinstance(recorded, dict) else {}
    sha256, size = fields.get("sha256"), fields.get("size")
    if not isinstance(sha256, str) or type(size) is not int:
        msg = f"{root / SOURCE} records no sha256 and size; {_reinstall(adapter, root)}"
        raise ProvisionError(msg)
    optional = {}
    for field in ("entry", "url", "final_url", "from_path", "installed_at"):
        value = fields.get(field)
        optional[field] = value if isinstance(value, str) else None
    return Source(sha256=sha256, size=size, **optional)


def _sha256_of(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def installed(adapter: Adapter, target: Target, cache_dir: Path) -> Installation | None:
    """`adapter`'s Installation for `target`, verified by its recorded sha256; None if absent.

    ProvisionError, naming the fix, if it is there but unrecorded or its binary changed.
    """
    root = root_of(adapter, target, cache_dir)
    if not root.exists():
        return None
    _record_unrecorded(root, adapter, target)
    source = _read_source(root, adapter)
    binary = root / adapter.binary
    actual = _sha256_of(binary) if binary.is_file() else "missing"
    if actual != source.sha256:
        msg = (
            f"{binary}: sha256 {actual} is not the recorded {source.sha256}; "
            f"{_reinstall(adapter, root)}"
        )
        raise ProvisionError(msg)
    return Installation(adapter=adapter.name, target=target, root=root, source=source)


def _write(adapter: Adapter, target: Target, cache_dir: Path, body: bytes, source: Source) -> None:
    """Check `body` and put it, with its SOURCE.json, at the root in one rename."""
    root = root_of(adapter, target, cache_dir)
    root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(dir=root.parent, prefix=f".{root.name}.", suffix=".part"))
    try:
        staging.chmod(0o755)
        (staging / adapter.binary).write_bytes(body)
        (staging / adapter.binary).chmod(0o755)
        adapter.check(staging / adapter.binary, target)
        recorded = dataclasses.asdict(source)
        (staging / SOURCE).write_text(json.dumps(recorded, indent=2) + "\n", encoding="utf-8")
        try:
            staging.rename(root)
        except OSError:
            if not root.is_dir():
                raise
            # Another install (another session) finished first: use theirs.
    finally:
        shutil.rmtree(staging, ignore_errors=True)  # gone already if the rename worked


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def install_entry(
    adapter: Adapter, target: Target, cache_dir: Path, entry: Entry, fetch: Fetch
) -> Installed:
    """Download `entry` into the cache, verified by every hash it pins; a no-op if installed."""
    if (entry.adapter, entry.target) != (adapter.name, target.minecraft_version):
        msg = (
            f"{entry} is a {entry.adapter} build for {entry.target}, "
            f"not {adapter.name} {target.minecraft_version}"
        )
        raise ProvisionError(msg)
    root = root_of(adapter, target, cache_dir)
    existing = installed(adapter, target, cache_dir)
    if existing is not None and existing.source is not None:
        if existing.source.entry == str(entry):
            message = (
                f"{entry} is already installed at {root} "
                f"(sha256 {existing.source.sha256}): nothing to do"
            )
            return Installed(existing, changed=False, message=message)
        msg = (
            f"{adapter.name} {target.minecraft_version} is already installed at {root}: "
            f"{describe(existing.source)}. To install {entry} instead, delete {root} and run "
            f"`{install_command(adapter.name, version=entry.version)}`"
        )
        raise ProvisionError(msg)
    try:
        download = fetch(entry.url)
    except OSError as error:  # urllib's URLError and TLS failures are OSErrors
        msg = (
            f"downloading {entry.url} failed: {error}\nDownload it another way (e.g. curl), "
            f"then run `{install_command(adapter.name, path='<file>')}`"
        )
        raise ProvisionError(msg) from error
    if not entry.matches(download.body):
        msg = (
            f"{entry.url} is not {entry}: sha256 {hashlib.sha256(download.body).hexdigest()}, "
            f"{len(download.body)} bytes. {entry.note}\nTo run that file anyway, save it and run "
            f"`{install_command(adapter.name, path='<file>')}`"
        )
        raise ProvisionError(msg)
    source = Source(
        sha256=hashlib.sha256(download.body).hexdigest(),
        size=len(download.body),
        entry=str(entry),
        url=entry.url,
        final_url=download.url,
        installed_at=_now(),
    )
    _write(adapter, target, cache_dir, download.body, source)
    return _done(adapter, target, cache_dir, f"installed {entry} from {entry.url}")


def install_from(
    adapter: Adapter, target: Target, cache_dir: Path, path: Path, registry: Registry
) -> Installed:
    """Install the file at `path`: record its sha256, and its Registry entry only if it is one."""
    try:
        body = path.read_bytes()
    except OSError as error:
        msg = f"cannot read {path}: {error}"
        raise ProvisionError(msg) from error
    sha256 = hashlib.sha256(body).hexdigest()
    matched = [
        entry
        for entry in registry.entries
        if (entry.adapter, entry.target) == (adapter.name, target.minecraft_version)
        and entry.matches(body)
    ]
    root = root_of(adapter, target, cache_dir)
    existing = installed(adapter, target, cache_dir)
    if existing is not None and existing.source is not None:
        if existing.source.sha256 == sha256:
            message = (
                f"{adapter.name} {target.minecraft_version} is already installed at {root} "
                f"with sha256 {sha256}: nothing to do"
            )
            return Installed(existing, changed=False, message=message)
        msg = (
            f"{adapter.name} {target.minecraft_version} is already installed at {root}: "
            f"{describe(existing.source)}. To install {path} instead, delete {root} and run "
            f"`{install_command(adapter.name, path=str(path))}`"
        )
        raise ProvisionError(msg)
    source = Source(
        sha256=sha256,
        size=len(body),
        entry=str(matched[0]) if matched else None,
        from_path=str(path.absolute()),
        installed_at=_now(),
    )
    _write(adapter, target, cache_dir, body, source)
    what = (
        f"the Registry entry {matched[0]}"
        if matched
        else "no Registry entry, so Reports name it by its sha256"
    )
    return _done(adapter, target, cache_dir, f"installed {path} (sha256 {sha256}; {what})")


def _done(adapter: Adapter, target: Target, cache_dir: Path, what: str) -> Installed:
    installation = installed(adapter, target, cache_dir)
    if installation is None:  # only if someone deleted it this very moment
        msg = f"{root_of(adapter, target, cache_dir)} vanished while installing it"
        raise ProvisionError(msg)
    return Installed(installation, changed=True, message=f"{what} into {installation.root}")


@dataclass(frozen=True, slots=True)
class Terminal:
    """Where require may ask its question: only if `stdin` is a TTY is anyone there to answer."""

    stdin: TextIO
    stdout: TextIO

    def say(self, text: str, end: str = "\n") -> None:
        """Show `text` at once (a question must be visible before its answer is read)."""
        self.stdout.write(text + end)
        self.stdout.flush()


def _answer(terminal: Terminal) -> bool | None:
    """True for yes, False for no, None at the end of input; re-asks anything else."""
    while True:
        line = terminal.stdin.readline()
        if not line:
            return None
        answer = line.strip().lower()
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        terminal.say("Please answer y or n. ", end="")


def require(
    adapter: Adapter,
    target: Target,
    cache_dir: Path,
    *,
    terminal: Terminal | None = None,
    fetch: Fetch = https_get,
) -> Installation:
    """`adapter`'s verified Installation for `target`; never installs one without saying so.

    If it is missing: with a `terminal` whose stdin is a TTY, asks whether to download its
    Registry entry (Y, announced and reported) or provision it yourself (N: prints the
    `--from` command, then ProvisionError naming it). Otherwise (no terminal, or stdin is
    no TTY; the default) ProvisionError at once, naming both commands; stdin is never read.
    """
    existing = installed(adapter, target, cache_dir)
    if existing is not None:
        return existing
    what = f"{adapter.name} {target.minecraft_version}"
    yourself = f"`{install_command(adapter.name, path='<file>')}`"
    try:
        entry = registry.official().resolve(adapter.name, target)
    except RegistryError as error:
        msg = f"{what} is not installed, and no registry entry can install it ({error}): "
        msg += f"provision it yourself with {yourself}"
        raise ProvisionError(msg) from error
    if terminal is None or not terminal.stdin.isatty():
        msg = (
            f"{what} is not installed, and without a terminal nothing is installed unasked. "
            f"Install {entry} with `{install_command(adapter.name)}`, "
            f"or provision it yourself with {yourself}"
        )
        raise ProvisionError(msg)
    terminal.say(
        f"{what} is not installed. Download {entry} (Y) or provision it yourself (N)? ", end=""
    )
    answer = _answer(terminal)
    if answer is None:
        terminal.say("")
        msg = (
            f"{what} is not installed and no answer came. Install {entry} with "
            f"`{install_command(adapter.name)}`, or provision it yourself with {yourself}"
        )
        raise ProvisionError(msg)
    if not answer:
        terminal.say(f"Provision it yourself, then run {yourself}")
        msg = f"{what} is not installed: provision it yourself, then run {yourself}"
        raise ProvisionError(msg)

    def announced(url: str) -> Download:
        terminal.say(f"downloading {url} ...")
        return fetch(url)

    done = install_entry(adapter, target, cache_dir, entry, announced)
    terminal.say(done.message)
    return done.installation
