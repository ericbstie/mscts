"""A fake Adapter for Run tests: its Instances are status_fake.py processes."""

import contextlib
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

from mscts.adapters.base import Installation, LaunchPlan
from mscts.bot import status_probe
from mscts.net import Endpoint
from mscts.run import Attached
from mscts.runner import free_endpoint, running
from mscts.spec import ServerSpec
from mscts.target import TARGET, Target

STATUS_FAKE = Path(__file__).with_name("status_fake.py")
TOKEN_VAR = "MSCTS_RUN_TOKEN"  # noqa: S105 - an env var name, not a secret


@dataclass
class FakeAdapter:
    """An Adapter whose Instances are tests/run/status_fake.py processes.

    The description the fake answers with is `description`, or else the spec's motd.
    Every ServerSpec it prepares is kept in `prepared`.
    """

    name: str
    token: str
    description: str | None = None
    prepared: list[ServerSpec] = field(default_factory=list)
    binary: str = "status_fake.py"

    def check(self, binary: Path, target: Target) -> None:
        """Every file is a fake server: nothing to check."""

    def prepare(self, installation: Installation, spec: ServerSpec, workdir: Path) -> LaunchPlan:
        assert installation.adapter == self.name
        workdir.mkdir(parents=True)
        self.prepared.append(spec)
        description = self.description if self.description is not None else spec.motd
        return LaunchPlan(
            # -I -S: isolated and without site, so it starts fast and sees only its env.
            argv=(
                sys.executable,
                "-I",
                "-S",
                str(STATUS_FAKE),
                spec.host,
                str(spec.port),
                description,
            ),
            cwd=workdir,
            env={TOKEN_VAR: self.token},
            endpoint=Endpoint(spec.host, spec.port),
            stop_stdin=b"stop\n",
        )


@contextlib.asynccontextmanager
async def attached(adapter: FakeAdapter, workdir: Path) -> AsyncIterator[Attached]:
    """A fake Instance of `adapter`, launched at the default ServerSpec, as a Run's Attached side.

    The test owns it: it is stopped when the block ends, not by the Run.
    """
    endpoint = free_endpoint()
    spec = ServerSpec(host=endpoint.host, port=endpoint.port)
    installation = Installation(adapter=adapter.name, target=TARGET, root=workdir)
    plan = adapter.prepare(installation, spec, workdir / "attached")
    async with running(plan, ready=status_probe(TARGET), ready_timeout=10.0):
        yield Attached(name=adapter.name, spec=spec)
