"""Research only: is a Candidate that crashes while a Group has its world frozen restarted?

Usage: crash_candidate.py [GROUP ...]

Made for #531. Plays a Run of the GROUPs (default `DEFAULT_GROUPS`, three tick-exact Groups that
freeze the world) once against vanilla and Pumpkin. Right after the second Group has frozen
Pumpkin's world, it sends SIGKILL to Pumpkin's process, as Pumpkin b70c7e1 exited when its
player-data save panicked. Then it prints the Report. Each Group should have its own Verdict, the
second should fail for Pumpkin, and a restart line should name Pumpkin after it. Exit code 0, or
1 if the second Group never froze Pumpkin's world, so nothing was killed. Run it under the live
lock:

    mise exec -- uv run python scripts/live_lock.py --tier candidate -- \
        mise exec -- uv run python scripts/research/crash_candidate.py
"""

import argparse
import asyncio
import contextlib
import os
import shutil
import signal
import sys
import tempfile
from collections.abc import Iterator, Sequence
from pathlib import Path
from time import perf_counter
from unittest import mock

from mscts import install, run
from mscts.cache import cache_dir
from mscts.cli import ADAPTERS
from mscts.group import GROUPS, Group, GroupContext, resolve
from mscts.net import Endpoint
from mscts.report import Report, render_text
from mscts.stats import SampleLog
from mscts.target import TARGET
from mscts.transcript import Transcript

DEFAULT_GROUPS = ("entities/pushing", "entities/item-merge", "entities/item-despawn")
"""Tick-exact Groups of one ServerSpec that freeze the world, which failed after Pumpkin crashed
(#531). One ServerSpec: one Instance pair, so one Candidate process to kill."""

CANDIDATE = "pumpkin"


def kill_under(workdir: Path, role: str) -> int:
    """SIGKILL the one process whose cwd is a `role` directory under `workdir`; return its pid.

    A Run launches each Instance in `<workdir>/<pair>/<role>` (`run._ROLES`).

    Raises:
        LookupError: No such process runs, or more than one does; none was killed.
    """
    found = [pid for pid in _pids() if _runs_in(pid, workdir, role)]
    if len(found) != 1:
        msg = f"{len(found)} processes run in a {role} directory under {workdir}, not 1"
        raise LookupError(msg)
    os.kill(found[0], signal.SIGKILL)
    return found[0]


def _pids() -> list[int]:
    return [int(entry.name) for entry in Path("/proc").iterdir() if entry.name.isdigit()]


def _runs_in(pid: int, workdir: Path, role: str) -> bool:
    """Whether process `pid` runs in a `role` directory under `workdir`."""
    try:
        cwd = Path(f"/proc/{pid}/cwd").readlink()
    except OSError:  # gone, or not ours to read
        return False
    return cwd.name == role and cwd.is_relative_to(workdir)


class Crash:
    """Kills the Candidate's process once the Group `group_id` has frozen its world."""

    def __init__(self, group_id: str, workdir: Path) -> None:
        """Watch for `group_id` on the Candidate, whose Instances run under `workdir`."""
        self.group_id = group_id
        self.workdir = workdir
        self.armed: Endpoint | None = None
        self.killed: int | None = None

    @contextlib.contextmanager
    def patched(self) -> Iterator[None]:
        """Arm when the Run plays the Group on the Candidate; fire when it has frozen the world."""
        play, freeze = run.run_group, GroupContext.freeze

        async def run_group(
            group: Group,
            endpoint: Endpoint,
            *,
            server: str,
            timeout_s: float = run.GROUP_TIMEOUT_S,
            samples: SampleLog | None = None,
        ) -> Transcript:
            if group.id == self.group_id and server == CANDIDATE and self.killed is None:
                self.armed = endpoint
            return await play(group, endpoint, server=server, timeout_s=timeout_s, samples=samples)

        async def frozen(context: GroupContext) -> None:
            await freeze(context)
            if context.endpoint == self.armed:
                self.armed = None
                self.killed = kill_under(self.workdir, "candidate")
                sys.stderr.write(f"crash_candidate: sent SIGKILL to {CANDIDATE} ({self.killed})\n")

        with (
            mock.patch.object(run, "run_group", run_group),
            mock.patch.object(GroupContext, "freeze", frozen),
        ):
            yield


def main(argv: Sequence[str] | None = None) -> int:
    """Play the Run, crash the Candidate in the second Group, and print the Report."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("groups", nargs="*", default=list(DEFAULT_GROUPS))
    arguments = parser.parse_args(argv)
    groups = resolve([GROUPS[group_id].id for group_id in arguments.groups])
    reference, candidate = (
        run.Server(adapter, install.require(adapter, TARGET, cache_dir()))
        for adapter in (ADAPTERS["vanilla"](), ADAPTERS[CANDIDATE]())
    )
    workdir = Path(tempfile.mkdtemp(prefix="crash-candidate-"))
    crash = Crash(groups[1].id, workdir)
    started = perf_counter()
    try:
        with crash.patched():
            result = asyncio.run(run.run_results(groups, reference, candidate, workdir=workdir))
    finally:
        shutil.rmtree(workdir)
    report = Report.of(result, target=TARGET, notes=(), elapsed_s=perf_counter() - started)
    sys.stdout.write(render_text(report))
    if crash.killed is None:
        sys.stderr.write(f"crash_candidate: {groups[1].id} never froze {CANDIDATE}'s world\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
