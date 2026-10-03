"""The Adapter contract: find a release, check a binary, prepare a LaunchPlan (ADR-0004).

Installations are install.py's (ADR-0008): an Adapter says where its builds are, and reads
what it needs through the `fetch` it is given, but never installs anything.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, override

from mscts.net import Endpoint
from mscts.spec import ServerSpec
from mscts.target import Target


class ProvisionError(RuntimeError):
    """An Installation could not be obtained or failed verification."""


class PrepareError(RuntimeError):
    """prepare cannot produce a LaunchPlan that meets the Adapter contract."""


@dataclass(frozen=True, slots=True)
class Build:
    """One build of a server, named as its publisher names it (ADR-0008)."""

    version: str  # "26.3"; Pumpkin's own "0.2.0+26.3-26.51"; "nightly"
    commit: str | None = None  # the full commit it was built from, where the publisher names one

    @override
    def __str__(self) -> str:
        """`26.3`, or `nightly 4426d11`: how Reports and commands name this build."""
        return self.version if self.commit is None else f"{self.version} {self.commit[:7]}"


@dataclass(frozen=True, slots=True)
class Release:
    """A build its publisher offers for download, and what the download must be (ADR-0008)."""

    build: Build
    url: str  # HTTPS
    sha1: str | None = None  # the publisher's own hash, where it publishes one (Mojang)
    size: int | None = None  # bytes, where the publisher states it


@dataclass(frozen=True, slots=True)
class Download:
    """The body of a fetched URL, and the URL it finally came from."""

    url: str  # the final URL, after every redirect
    body: bytes


type Fetch = Callable[[str], Download]
"""How an Adapter and install.py read a URL: fetch.https_get, or a fake in tests."""


@dataclass(frozen=True, slots=True)
class Source:
    """Where an Installation's binary came from, as its SOURCE.json records it (ADR-0008)."""

    sha256: str  # of the installed binary; every later use verifies the binary by it
    size: int
    version: str | None = None  # its Build's (None only in a SOURCE.json written before #156)
    commit: str | None = None  # its Build's
    url: str | None = None  # the URL it was downloaded from (its Release's)
    final_url: str | None = None  # where that URL finally redirected to
    from_path: str | None = None  # the `--from` file it was copied from
    installed_at: str | None = None  # ISO 8601, UTC

    @property
    def build(self) -> Build | None:
        """The Build it records, if it records one."""
        return None if self.version is None else Build(version=self.version, commit=self.commit)


@dataclass(frozen=True, slots=True)
class Installation:
    """The binaries installed for an Adapter and a Target, cached on disk (install.py)."""

    adapter: str
    target: Target
    root: Path  # immutable, inside the cache dir
    source: Source | None = None  # None only for an Installation built by hand (tests)


@dataclass(frozen=True, slots=True)
class LaunchPlan:
    """How to launch one Instance. It contains no process handling."""

    argv: tuple[str, ...]
    cwd: Path
    env: Mapping[str, str]
    endpoint: Endpoint
    stop_stdin: bytes | None  # graceful stop via stdin (b"stop\n"); None means SIGTERM


class Adapter(Protocol):
    """Translates a ServerSpec into one server's native config. Never runs a process."""

    name: str
    binary: str  # the one file an Installation holds besides SOURCE.json ("server.jar")

    def release(self, target: Target, version: str | None, fetch: Fetch) -> Release:
        """The latest build for `target`, or the build `version` names (`<name>@<version>`).

        ProvisionError, naming what would work, if that build is not for `target` or cannot
        be downloaded.
        """
        ...

    def check(self, binary: Path, target: Target) -> Build:
        """The Build `binary` names; ProvisionError unless this Adapter can run it for `target`.

        A build for another Minecraft version is refused, naming both versions.
        """
        ...

    def prepare(self, installation: Installation, spec: ServerSpec, workdir: Path) -> LaunchPlan:
        """Write the complete native config for `spec` into `workdir`."""
        ...
