"""Research only: which `set_time` the `time/sleep` lie-down window counts, against the test fake.

Usage (a pytest module, given by path, so the unit tier never collects it; `pythonpath` adds the
checkout, so that it imports the test module's fake):

    SLEEP_COUNT_OUT=<dir> SLEEP_COUNT_PLAYS=24 python3 scripts/repeat.py --times 10 --stress \
        -- -o "pythonpath=tests ." scripts/research/sleep_count.py -n 8

`SLEEP_COUNT_PLAYS` plays run in each pytest run, side by side with `-n`, which loads the host
as `mise run check` does. One play a run, under `--stress` alone, did not come up short in 35.

Made for #454. `tests/group/test_time.py` plays `time/sleep` against its fake `TimeServer`,
which sends the clock a `set_time` every `TIME_TICKS` ticks, and asserts that at least
`_QUIET_TIMES` of them were read inside the first window, the one in which the sleeper lies down
with 100% needed. That count came up short under load once.

Each run plays the Group once with a fresh fake and reads its Transcript: the window's open and
close Marks, each Bot's last barrier answer before the open, and every `set_time` the clock read
from its last answer before the open to the close. The Group's `_count_set_time` takes the first
`_QUIET_TIMES` of those. Each is placed against the open Mark:

- `before`: read after the clock's last answer but before the open, so it is setup, outside the
  window, and yet the Group counted it;
- `at`: stamped at the open Mark itself, inside the window as Compare sees it (a packet stamped
  at a Mark's time is after the Mark);
- `inside`: after the open Mark.

When fewer than `_QUIET_TIMES` were read strictly between the Marks (the test's own count), the
run writes the stamps as JSON to `$SLEEP_COUNT_OUT` (one file a run) and fails, so `repeat.py`
counts it.
"""

import asyncio
import json
import os
import time
from pathlib import Path

import pytest

from mscts.codec.packets import Direction
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN
from mscts.groups.time import _QUIET_TIMES
from mscts.transcript import Transcript
from tests.group.test_time import CLOCK, SET_TIME, SLEEPER, TimeServer, _play

_ANSWER = "minecraft:award_stats"
_OUT = "SLEEP_COUNT_OUT"
_PLAYS = "SLEEP_COUNT_PLAYS"
"""How many plays each run makes: with `-n`, they run side by side and load the host too."""


def _clientbound(transcript: Transcript, bot: str, name: str) -> list[int]:
    """When `bot` read each packet called `name`."""
    return [
        event.t_ns
        for event in transcript.events
        if event.bot == bot
        and event.packet.direction is Direction.CLIENTBOUND
        and event.packet.name == name
    ]


def _mark(transcript: Transcript, label: str) -> int:
    """The first Mark called exactly `label`, or starting with it and a space."""
    return next(
        m.t_ns for m in transcript.marks if m.label == label or m.label.startswith(f"{label} ")
    )


def _window(transcript: Transcript) -> tuple[int, int]:
    """The first window's open Mark, and its close Mark that names no Bot."""
    opened = _mark(transcript, OBSERVE_OPEN)
    return opened, next(m.t_ns for m in transcript.marks if m.label == OBSERVE_CLOSE)


def strictly_inside(transcript: Transcript) -> int:
    """How many `set_time` the clock read strictly between the first window's Marks."""
    opened, closed = _window(transcript)
    return len([t for t in _clientbound(transcript, CLOCK, SET_TIME) if opened < t < closed])


def stamps(transcript: Transcript) -> dict[str, object]:
    """The first window's stamps, in nanoseconds since the Transcript started."""
    opened, closed = _window(transcript)
    answers = {
        bot: max(t for t in _clientbound(transcript, bot, _ANSWER) if t < opened)
        for bot in (CLOCK, SLEEPER)
    }
    times = [t for t in _clientbound(transcript, CLOCK, SET_TIME) if answers[CLOCK] < t < closed]
    counted = times[:_QUIET_TIMES]
    return {
        "opened": opened,
        "closed": closed,
        "clock_close": _mark(transcript, f"{OBSERVE_CLOSE} {CLOCK}"),
        "answers": answers,
        "set_time": times,
        "counted": {
            "before": [t for t in counted if t < opened],
            "at": [t for t in counted if t == opened],
            "inside": [t for t in counted if t > opened],
        },
        "strictly_inside": strictly_inside(transcript),
    }


@pytest.mark.parametrize("play", range(int(os.environ.get(_PLAYS, "1"))))
def test_the_lie_down_window_holds_the_counted_set_time(play: int) -> None:
    """Play `time/sleep` once; on a short count, write the stamps and fail."""
    del play
    transcript = asyncio.run(_play("time/sleep", TimeServer()))
    found = stamps(transcript)
    out = Path(os.environ.get(_OUT, "."))
    out.mkdir(parents=True, exist_ok=True)
    with (out / "runs.jsonl").open("a") as runs:
        runs.write(json.dumps(found) + "\n")
    if strictly_inside(transcript) >= _QUIET_TIMES:
        return
    (out / f"short-{time.time_ns()}.json").write_text(json.dumps(found, indent=2))
    msg = f"the test's count came up short: {json.dumps(found)}"
    raise AssertionError(msg)
