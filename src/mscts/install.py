"""Installations (ADR-0008): explicit, idempotent, and honest about where a binary came from.

An Installation is `<cache>/<adapter>/<Minecraft version>/`: the Adapter's one binary and
SOURCE.json, which records its Build, its sha256 and its source (the URL its Adapter found
it at, or a `--from` file). It is written in one rename, complete or not at all, and never
refreshed: to change it, delete it and install again.
"""

import dataclasses
import datetime
import hashlib
import http.client
import json
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from mscts.adapters.base import (
    Adapter,
    Build,
    Download,
    Fetch,
    Installation,
    ProvisionError,
    Release,
    Source,
)
from mscts.adapters.fetch import https_get
from mscts.target import Target

SOURCE = "SOURCE.json"
_SHORT = 7  # the fewest characters of a commit that name it, as git's short commit


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
    """The exact `mscts adapter install` command line for a build or a `--from` file."""
    if path is not None:
        return f"mscts adapter install {adapter} --from {path}"
    return f"mscts adapter install {adapter}" + (f"@{version}" if version else "")


def _reinstall(adapter: Adapter, root: Path) -> str:
    return f"delete {root} and run `{install_command(adapter.name)}` again"


def describe(source: Source) -> str:
    """Where an Installation came from, in words: its build, and its URL or `--from` file."""
    build = source.build or "an unknown build"
    origin = source.from_path or source.url
    if origin is None:
        return f"{build} (sha256 {source.sha256})"
    return f"{build}, from {origin} (sha256 {source.sha256})"


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
    for field in ("version", "commit", "url", "final_url", "from_path", "installed_at"):
        value = fields.get(field)
        optional[field] = value if isinstance(value, str) else None
    return Source(sha256=sha256, size=size, **optional)


def _sha256_of(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def installed(adapter: Adapter, target: Target, cache_dir: Path) -> Installation | None:
    """`adapter`'s Installation for `target`, verified by its recorded sha256; None if absent.

    ProvisionError, naming the fix, if it is there but unrecorded or its binary changed. One
    recorded before Builds were names the Build its binary names (read, never written).
    """
    root = root_of(adapter, target, cache_dir)
    if not root.exists():
        return None
    source = _read_source(root, adapter)
    binary = root / adapter.binary
    actual = _sha256_of(binary) if binary.is_file() else "missing"
    if actual != source.sha256:
        msg = (
            f"{binary}: sha256 {actual} is not the recorded {source.sha256}; "
            f"{_reinstall(adapter, root)}"
        )
        raise ProvisionError(msg)
    if source.version is None:
        build = adapter.check(binary, target)
        source = dataclasses.replace(source, version=build.version, commit=build.commit)
    return Installation(adapter=adapter.name, target=target, root=root, source=source)


def _write(
    adapter: Adapter,
    target: Target,
    cache_dir: Path,
    body: bytes,
    source: Callable[[Build], Source],
) -> None:
    """Check `body`, then put it and the SOURCE.json `source` makes of its Build in one rename."""
    root = root_of(adapter, target, cache_dir)
    root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(dir=root.parent, prefix=f".{root.name}.", suffix=".part"))
    try:
        staging.chmod(0o755)
        (staging / adapter.binary).write_bytes(body)
        (staging / adapter.binary).chmod(0o755)
        recorded = dataclasses.asdict(source(adapter.check(staging / adapter.binary, target)))
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


def _names(build: Build, version: str) -> bool:
    """Whether `<adapter>@<version>` names `build`: its version, or a commit's first 7+."""
    commit = build.commit or ""
    return version == build.version or (len(version) >= _SHORT and commit.startswith(version))


def _already(existing: Installation, adapter: Adapter, version: str | None) -> Installed:
    """A no-op if `version` (None: any) names the installed build; else ProvisionError."""
    root, source = existing.root, existing.source
    build = None if source is None else source.build
    if source is None or build is None:  # only an Installation built by hand (tests)
        msg = f"{root} records no build; {_reinstall(adapter, root)}"
        raise ProvisionError(msg)
    if version is None or _names(build, version):
        message = (
            f"{adapter.name} {build} is already installed at {root} (sha256 {source.sha256}): "
            f"nothing to do. For a newer build, delete {root} and install again."
        )
        return Installed(existing, changed=False, message=message)
    msg = (
        f"{adapter.name} {existing.target.minecraft_version} is already installed at {root}: "
        f"{adapter.name} {describe(source)}. To install {adapter.name}@{version} instead, "
        f"delete {root} and run `{install_command(adapter.name, version=version)}`"
    )
    raise ProvisionError(msg)


def _published(adapter: Adapter, release: Release, download: Download) -> None:
    """ProvisionError unless `download` has the sha1 and size its publisher lists, if any."""
    body = download.body
    sha1 = hashlib.sha1(body, usedforsecurity=False).hexdigest()  # the publisher's own check
    if (release.size is None or len(body) == release.size) and (
        release.sha1 is None or sha1 == release.sha1
    ):
        return
    msg = (
        f"{release.url} is not {adapter.name} {release.build}: sha1 {sha1}, {len(body)} bytes, "
        f"where its publisher lists sha1 {release.sha1}, {release.size} bytes.\n"
        f"To run that file anyway, save it and run "
        f"`{install_command(adapter.name, path='<file>')}`"
    )
    raise ProvisionError(msg)


def install_release(
    adapter: Adapter, target: Target, cache_dir: Path, version: str | None, fetch: Fetch
) -> Installed:
    """Download the latest build for `target` (or `version`'s) into the cache, verified.

    A no-op if that build is installed already (with `version` None: whatever build is).
    """
    existing = installed(adapter, target, cache_dir)
    if existing is not None:
        return _already(existing, adapter, version)
    yourself = f"`{install_command(adapter.name, path='<file>')}`"
    try:
        release = adapter.release(target, version, fetch)
        download = fetch(release.url)
    except (OSError, http.client.HTTPException) as error:  # URLError, TLS, a cut-off body
        msg = (
            f"downloading failed: {error}\n"
            f"Download the build another way (e.g. curl), then run {yourself}"
        )
        raise ProvisionError(msg) from error
    _published(adapter, release, download)

    def source(build: Build) -> Source:
        if release.build.commit is not None and build.commit != release.build.commit:
            msg = (
                f"{release.url} is not {adapter.name} {release.build}: it is {adapter.name} "
                f"{build}. A new build may be being published: try again in a few minutes, "
                f"or run {yourself}"
            )
            raise ProvisionError(msg)
        return Source(
            sha256=hashlib.sha256(download.body).hexdigest(),
            size=len(download.body),
            version=release.build.version,
            commit=release.build.commit,
            url=release.url,
            final_url=download.url,
            installed_at=_now(),
        )

    _write(adapter, target, cache_dir, download.body, source)
    what = f"installed {adapter.name} {release.build} from {release.url}"
    return _done(adapter, target, cache_dir, what)


def install_from(adapter: Adapter, target: Target, cache_dir: Path, path: Path) -> Installed:
    """Install the file at `path`, recording its sha256 and the Build it names."""
    try:
        body = path.read_bytes()
    except OSError as error:
        msg = f"cannot read {path}: {error}"
        raise ProvisionError(msg) from error
    sha256 = hashlib.sha256(body).hexdigest()
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
            f"{adapter.name} {describe(existing.source)}. To install {path} instead, delete "
            f"{root} and run `{install_command(adapter.name, path=str(path))}`"
        )
        raise ProvisionError(msg)
    named: list[Build] = []

    def source(build: Build) -> Source:
        named.append(build)
        return Source(
            sha256=sha256,
            size=len(body),
            version=build.version,
            commit=build.commit,
            from_path=str(path.absolute()),
            installed_at=_now(),
        )

    _write(adapter, target, cache_dir, body, source)
    what = f"installed {path} ({adapter.name} {named[0]}, sha256 {sha256})"
    return _done(adapter, target, cache_dir, what)


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
    latest build (Y: every download announced, then reported) or provision it yourself (N:
    prints the `--from` command, then ProvisionError naming it). Otherwise (no terminal, or
    stdin is no TTY; the default) ProvisionError at once, naming both commands; stdin is
    never read.
    """
    existing = installed(adapter, target, cache_dir)
    if existing is not None:
        return existing
    what = f"{adapter.name} {target.minecraft_version}"
    yourself = f"`{install_command(adapter.name, path='<file>')}`"
    latest = f"its latest build with `{install_command(adapter.name)}`"
    if terminal is None or not terminal.stdin.isatty():
        msg = (
            f"{what} is not installed, and without a terminal nothing is installed unasked. "
            f"Install {latest}, or provision it yourself with {yourself}"
        )
        raise ProvisionError(msg)
    terminal.say(
        f"{what} is not installed. Download its latest build (Y) or provision it yourself (N)? ",
        end="",
    )
    answer = _answer(terminal)
    if answer is None:
        terminal.say("")
        msg = (
            f"{what} is not installed and no answer came. Install {latest}, "
            f"or provision it yourself with {yourself}"
        )
        raise ProvisionError(msg)
    if not answer:
        terminal.say(f"Provision it yourself, then run {yourself}")
        msg = f"{what} is not installed: provision it yourself, then run {yourself}"
        raise ProvisionError(msg)

    def announced(url: str) -> Download:
        terminal.say(f"downloading {url} ...")
        return fetch(url)

    done = install_release(adapter, target, cache_dir, None, announced)
    terminal.say(done.message)
    return done.installation
