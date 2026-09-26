"""The leak-guard pattern (Worker contract, docs/PROCESS.md), for any process-starting test.

Tag a spawned process's environment with a per-test (or per-session) token, then use
`kill_survivors` at teardown: it waits a moment for a process that is already
stopping to actually exit, SIGKILLs anything still tagged with the token, and
returns what it had to kill (empty if nothing leaked).
"""

import contextlib
import os
import signal
import time
from pathlib import Path

DEFAULT_PROC = Path("/proc")


def tagged_pids(token: str, *, proc_dir: Path = DEFAULT_PROC) -> list[int]:
    """Running processes whose environment holds `token` (an exact "NAME=value" entry)."""
    needle = token.encode()
    pids = []
    for entry in proc_dir.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            environ = (entry / "environ").read_bytes()  # empty for a zombie
        except OSError:  # gone meanwhile
            continue
        if needle in environ.split(b"\0"):
            pids.append(int(entry.name))
    return pids


def kill_survivors(token: str, *, within: float = 1.0, proc_dir: Path = DEFAULT_PROC) -> list[int]:
    """SIGKILL every process still tagged with `token` after `within` seconds.

    Gives a process that is already stopping (e.g. mid-graceful-shutdown) up to
    `within` seconds to exit on its own before treating it as a leak. Returns the
    pids it had to kill (empty: nothing leaked).
    """
    deadline = time.monotonic() + within
    leaked = tagged_pids(token, proc_dir=proc_dir)
    while leaked and time.monotonic() < deadline:
        time.sleep(0.01)
        leaked = tagged_pids(token, proc_dir=proc_dir)
    for pid in leaked:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
    return leaked
