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
    UnavailableError,
    UnsupportedError,
    build_it_yourself,
    install_command,
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


type Clock = Callable[[], datetime.datetime]
"""The time now, timezone-aware: utc_now, or a fixed time in tests."""


def utc_now() -> datetime.datetime:
    """The time now, in UTC: the Clock outside tests."""
    return datetime.datetime.now(datetime.UTC)


def _stamp(moment: datetime.datetime) -> str:
    """`moment` as SOURCE.json records it: ISO 8601, to the second."""
    return moment.isoformat(timespec="seconds")


def _names(build: Build, version: str) -> bool:
    """Whether `<adapter>@<version>` names `build`: its version, or a commit's first 7+."""
    commit = build.commit or ""
    return version == build.version or (len(version) >= _SHORT and commit.startswith(version))


def _unchanged(existing: Installation, adapter: Adapter, version: str | None) -> Installed | None:
    """A no-op if `version` (None: any) names the installed build, else None."""
    root, source = existing.root, existing.source
    build = None if source is None else source.build
    if source is None or build is None:  # only an Installation built by hand (tests)
        msg = f"{root} records no build; {_reinstall(adapter, root)}"
        raise ProvisionError(msg)
    if version is not None and not _names(build, version):
        return None
    message = (
        f"{adapter.name} {build} is already installed at {root} (sha256 {source.sha256}): "
        f"nothing to do. To check for a newer build, delete {root} and install again."
    )
    return Installed(existing, changed=False, message=message)


def _vacant(existing: Installation | None, adapter: Adapter, version: str | None) -> None:
    """ProvisionError, naming the fix, if another build is installed: never replaced silently."""
    if existing is None or existing.source is None:
        return
    root = existing.root
    msg = (
        f"{adapter.name} {existing.target.minecraft_version} is already installed at {root}: "
        f"{adapter.name} {describe(existing.source)}. To install {adapter.name}@{version} "
        f"instead, delete {root} and run `{install_command(adapter.name, version=version)}`"
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


def install_release(  # noqa: PLR0913 - the IO it does (fetch, now) is passed in, not read
    adapter: Adapter,
    target: Target,
    cache_dir: Path,
    version: str | None,
    fetch: Fetch,
    *,
    now: Clock = utc_now,
) -> Installed:
    """Download the latest build for `target` (or `version`'s) into the cache, verified.

    A no-op if that build is installed already (with `version` None: whatever build is).
    With another build installed, the Adapter's refusal of `version` comes first, then
    ProvisionError naming how to replace it. What is recorded is what the file names.
    """
    version = None if version in adapter.latest_aliases else version
    existing = installed(adapter, target, cache_dir)
    unchanged = None if existing is None else _unchanged(existing, adapter, version)
    if unchanged is not None:
        return unchanged
    release = _release(adapter, target, version, fetch)
    download = _verified_download(adapter, release, fetch)
    installed_at = _stamp(now())

    def source(build: Build) -> Source:
        downloaded = _what_was_downloaded(adapter.name, release, build, version)
        _vacant(existing, adapter, version)
        return _downloaded_source(release, download, downloaded, installed_at)

    try:
        _write(adapter, target, cache_dir, download.body, source)
    except UnsupportedError as error:  # it named the staging path, gone by now
        raise _unsupported_download(adapter.name, version, release.url, error) from error
    return _done(adapter, target, cache_dir)


def _release(adapter: Adapter, target: Target, version: str | None, fetch: Fetch) -> Release:
    """`adapter.release`, whose every failure is a ProvisionError naming `--from`.

    An Adapter gives the facts; mscts adds the hint (UnavailableError words its own).
    """
    yourself = f"`{install_command(adapter.name, path='<file>')}`"
    try:
        return adapter.release(target, version, fetch)
    except (OSError, http.client.HTTPException) as error:  # URLError, TLS, a cut-off body
        raise _download_failed(error, yourself) from error
    except (UnsupportedError, UnavailableError):
        raise
    except ProvisionError as error:
        msg = f"{error}\n{build_it_yourself(adapter.name)}"
        raise ProvisionError(msg) from error
    except Exception as error:  # a garbled page, or the Adapter's own bug: never a traceback
        msg = (
            f"{_asked(adapter.name, version)} could not be found: {type(error).__name__}: "
            f"{error}\n"
            f"Download the build another way, then run {yourself}"
        )
        raise ProvisionError(msg) from error


def _asked(adapter: str, version: str | None) -> str:
    """What the user asked to install, in words: `pumpkin's latest build`, `pumpkin@4426d11`."""
    return f"{adapter}'s latest build" if version is None else f"{adapter}@{version}"


def _unsupported_download(
    adapter: str, version: str | None, url: str, error: UnsupportedError
) -> ProvisionError:
    """`error` about a downloaded file, said of what was asked for, and how to get another."""
    asked = UnsupportedError(
        f"{_asked(adapter, version)} ({url})", target=error.target, actual=error.actual
    )
    return ProvisionError(f"{asked}\n{build_it_yourself(adapter)}")


def _download_failed(error: Exception, yourself: str) -> ProvisionError:
    """The error for a download that failed with `error`, naming the `yourself` command."""
    msg = (
        f"downloading failed: {error}\n"
        f"Download the build another way (e.g. curl), then run {yourself}"
    )
    return ProvisionError(msg)


def _verified_download(adapter: Adapter, release: Release, fetch: Fetch) -> Download:
    """`release`'s file, with the sha1 and size its publisher lists, if any."""
    try:
        download = fetch(release.url)
    except (OSError, http.client.HTTPException) as error:  # URLError, TLS, a cut-off body
        yourself = f"`{install_command(adapter.name, path='<file>')}`"
        raise _download_failed(error, yourself) from error
    _published(adapter, release, download)
    return download


def _what_was_downloaded(
    adapter: str, release: Release, build: Build, version: str | None
) -> Build:
    """The build a downloaded file is: its release's name, and the commit the file names.

    The release's commit only found the file. ProvisionError if the file names none where
    its release does; UnavailableError if it is not the build `version` names.
    """
    if release.build.commit is not None and build.commit is None:
        msg = (
            f"{release.url} names no commit, so which {adapter} {release.build.version} it is "
            f"cannot be told.\n{build_it_yourself(adapter)}"
        )
        raise ProvisionError(msg)
    downloaded = Build(version=release.build.version, commit=build.commit)
    if version is not None and not _names(downloaded, version):
        raise UnavailableError(adapter, version, latest=downloaded)
    return downloaded


def _downloaded_source(
    release: Release, download: Download, build: Build, installed_at: str
) -> Source:
    """What SOURCE.json records for `download` of `release`, the file being `build`."""
    return Source(
        sha256=hashlib.sha256(download.body).hexdigest(),
        size=len(download.body),
        version=build.version,
        commit=build.commit,
        url=release.url,
        final_url=download.url,
        installed_at=installed_at,
    )


def install_from(
    adapter: Adapter, target: Target, cache_dir: Path, path: Path, *, now: Clock = utc_now
) -> Installed:
    """Install the file at `path`, recording its sha256 and the Build it names.

    A file the Adapter cannot run is refused first, naming `path`, whatever is installed.
    """
    body = _read(path)
    adapter.check(path, target)  # its errors name the user's file, and come first
    existing = installed(adapter, target, cache_dir)
    if existing is not None and existing.source is not None:
        return _same_file(existing, adapter, path, hashlib.sha256(body).hexdigest())
    installed_at = _stamp(now())

    def source(build: Build) -> Source:
        return _supplied_source(path, body, build, installed_at)

    _write(adapter, target, cache_dir, body, source)
    return _done(adapter, target, cache_dir)


def _read(path: Path) -> bytes:
    """The bytes of the file at `path`; ProvisionError, naming it, if it cannot be read."""
    try:
        return path.read_bytes()
    except OSError as error:
        msg = f"cannot read {path}: {error}"
        raise ProvisionError(msg) from error


def _same_file(existing: Installation, adapter: Adapter, path: Path, sha256: str) -> Installed:
    """A no-op if `existing` holds the file at `path` (by `sha256`); else ProvisionError."""
    root, source = existing.root, existing.source
    if source is not None and source.sha256 == sha256:
        message = (
            f"{adapter.name} {existing.target.minecraft_version} is already installed at "
            f"{root} with sha256 {sha256}: nothing to do"
        )
        return Installed(existing, changed=False, message=message)
    described = "an unknown build" if source is None else describe(source)
    msg = (
        f"{adapter.name} {existing.target.minecraft_version} is already installed at {root}: "
        f"{adapter.name} {described}. To install {path} instead, delete "
        f"{root} and run `{install_command(adapter.name, path=str(path))}`"
    )
    raise ProvisionError(msg)


def _supplied_source(path: Path, body: bytes, build: Build, installed_at: str) -> Source:
    """What SOURCE.json records for the file at `path`, holding `body`, which is `build`."""
    return Source(
        sha256=hashlib.sha256(body).hexdigest(),
        size=len(body),
        version=build.version,
        commit=build.commit,
        from_path=str(path.absolute()),
        installed_at=installed_at,
    )


def _done(adapter: Adapter, target: Target, cache_dir: Path) -> Installed:
    """The Installation now there, described by its own record: another install may have won."""
    installation = installed(adapter, target, cache_dir)
    source = None if installation is None else installation.source
    if installation is None or source is None:  # only if someone deleted it this very moment
        msg = f"{root_of(adapter, target, cache_dir)} vanished while installing it"
        raise ProvisionError(msg)
    if source.from_path is not None:
        what = (
            f"installed {source.from_path} ({adapter.name} {source.build}, sha256 {source.sha256})"
        )
    else:
        what = f"installed {adapter.name} {source.build} from {source.url}"
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
