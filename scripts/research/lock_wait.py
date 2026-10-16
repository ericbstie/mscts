#!/usr/bin/env python3
"""Research only: how long a short live run waits behind a series of runs (#411).

Usage:
    uv run scripts/research/lock_wait.py [--runs N] [--run-seconds S] [--short-after S]

Under a temporary cache dir, it starts a fake series (`--runs` runs of a `--run-seconds`
sleep, through `scripts/repeat.py` with a stand-in `uv` that only sleeps), then, `--short-after`
seconds later, a short run (`scripts/live_lock.py -- python -c pass`), and prints how long the
short run took. It does this twice:

- `whole series`: the series under one outer `live_lock.py`, as before #411.
- `per run`: `repeat.py --live-lock`, which takes the lock for each run.

The short run is also timed with the lock free, because starting Python and importing `mscts`
is part of its time: its wait is the difference. No real Self-check runs.
"""

import argparse
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
STAND_IN_UV = "#!/bin/sh\nexec sleep {seconds}\n"
MODES = ("whole series", "per run")


def series_command(mode: str, runs: int) -> list[str]:
    """The fake series: `repeat.py` for `runs` runs, under one outer lock or one lock per run."""
    repeat = [sys.executable, str(SCRIPTS / "repeat.py"), "--times", str(runs)]
    if mode == "per run":
        return [*repeat, "--live-lock", "--", "stand-in"]
    return [sys.executable, str(SCRIPTS / "live_lock.py"), "--", *repeat, "--", "stand-in"]


def short_run() -> list[str]:
    """A live run that does nothing, through the same wrapper a live tier uses."""
    return [sys.executable, str(SCRIPTS / "live_lock.py"), "--", sys.executable, "-c", "pass"]


def seconds_to_finish(command: list[str], env: dict[str, str]) -> float:
    """Run `command` to its end and return how long it took."""
    start = time.monotonic()
    subprocess.run(command, env=env, check=True, capture_output=True)  # noqa: S603
    return time.monotonic() - start


def short_run_behind(mode: str, env: dict[str, str], arguments: argparse.Namespace) -> float:
    """Start the series, start the short run `--short-after` seconds later, time the short run."""
    series = subprocess.Popen(  # noqa: S603
        series_command(mode, arguments.runs),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(arguments.short_after)
        return seconds_to_finish(short_run(), env)
    finally:
        series.wait()


def stand_in_environment(scratch: Path, run_seconds: float) -> dict[str, str]:
    """This process's environment, with a `uv` that sleeps and a cache under `scratch`.

    The lock variables are dropped: inside a holder's command every lock would be skipped.
    """
    stand_in = scratch / "bin" / "uv"
    stand_in.parent.mkdir()
    stand_in.write_text(STAND_IN_UV.format(seconds=run_seconds))
    stand_in.chmod(0o755)
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"MSCTS_LIVE_LOCK_HELD", "MSCTS_LIVE_LOCK"}
    }
    env["PATH"] = f"{stand_in.parent}{os.pathsep}{env['PATH']}"
    env["MSCTS_CACHE"] = str(scratch / "cache")
    return env


def main(argv: Sequence[str] | None = None) -> None:
    """Print the short run's time with a free lock, then behind each kind of series."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=6)
    parser.add_argument("--run-seconds", type=float, default=2.0)
    parser.add_argument("--short-after", type=float, default=3.0)
    arguments = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="mscts-lock-wait-") as scratch:
        env = stand_in_environment(Path(scratch), arguments.run_seconds)
        free = seconds_to_finish(short_run(), env)
        print(f"short run, lock free: {free:.2f} s")
        for mode in MODES:
            behind = short_run_behind(mode, env, arguments)
            print(f"{mode}: the short run took {behind:.2f} s, so it waited {behind - free:.2f} s")


if __name__ == "__main__":
    main()
