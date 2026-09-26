"""The Adapter contract: check a binary, prepare a LaunchPlan (ADR-0004).

Installations are install.py's (ADR-0008): an Adapter never downloads anything.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from mscts.net import Endpoint
from mscts.spec import ServerSpec
from mscts.target import Target


class ProvisionError(RuntimeError):
    """An Installation could not be obtained or failed verification."""


class PrepareError(RuntimeError):
    """prepare cannot produce a LaunchPlan that meets the Adapter contract."""


@dataclass(frozen=True, slots=True)
class Source:
    """Where an Installation's binary came from, as its SOURCE.json records it (ADR-0008)."""

    sha256: str  # of the installed binary; every later use verifies the binary by it
    size: int
    entry: str | None = None  # the Registry entry it hash-matches ("pumpkin nightly-48cba7ee")
    url: str | None = None  # the URL it was downloaded from (the entry's)
    final_url: str | None = None  # where that URL finally redirected to
    from_path: str | None = None  # the `--from` file it was copied from
    installed_at: str | None = None  # ISO 8601, UTC


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

    def check(self, binary: Path, target: Target) -> None:
        """Raise ProvisionError unless `binary` is a server this Adapter can run for `target`."""
        ...

    def prepare(self, installation: Installation, spec: ServerSpec, workdir: Path) -> LaunchPlan:
        """Write the complete native config for `spec` into `workdir`."""
        ...
