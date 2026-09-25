"""The Adapter contract: provision an Installation, prepare a LaunchPlan (ADR-0004)."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from mscts.net import Endpoint
from mscts.spec import ServerSpec
from mscts.target import Target


@dataclass(frozen=True, slots=True)
class Installation:
    """The binaries an Adapter has provisioned for a Target, cached on disk."""

    adapter: str
    target: Target
    root: Path  # immutable, inside the cache dir


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

    def provision(self, target: Target, cache_dir: Path) -> Installation:
        """Obtain the binaries for `target` into `cache_dir`. Idempotent and hash-verified."""
        ...

    def prepare(self, installation: Installation, spec: ServerSpec, workdir: Path) -> LaunchPlan:
        """Write the complete native config for `spec` into `workdir`."""
        ...
