"""Measurements: timings computed from a Transcript's Marks, and their summary statistics."""

import math
import statistics
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from mscts.transcript import Transcript

_START = ":start"
_END = ":end"
_NS_PER_MS = 1_000_000


@dataclass(frozen=True, slots=True)
class Measurement:
    """One timing or size a Group (or the Run) measured on one Instance.

    Attributes:
        name: What was measured, e.g. `status.rtt` or `instance.startup`.
        unit: `ms`, `bytes` or `count`.
        value: The value, in `unit`.
    """

    name: str
    unit: Literal["ms", "bytes", "count"]
    value: float


@dataclass(frozen=True, slots=True)
class Stats:
    """A summary of several values of one Measurement.

    Attributes:
        n: How many values.
        median: Their median (the mean of the two middle ones for an even `n`).
        p95: Their 95th percentile, by nearest rank: the smallest value at least 95% of
            the values are at or below.
    """

    n: int
    median: float
    p95: float


def measurements(transcript: Transcript) -> list[Measurement]:
    """The spans of `transcript`, in milliseconds, in the order they started.

    A span is a `<name>:start` Mark and the next `<name>:end` Mark after it. A start
    with no end (its body raised) yields nothing; so does an end with no start.
    """
    open_spans: dict[str, deque[int]] = {}
    found: list[tuple[int, Measurement]] = []
    for mark in transcript.marks:
        if mark.label.endswith(_START):
            name = mark.label.removesuffix(_START)
            open_spans.setdefault(name, deque()).append(mark.t_ns)
        elif mark.label.endswith(_END):
            starts = open_spans.get(mark.label.removesuffix(_END))
            if starts:
                start = starts.popleft()
                name = mark.label.removesuffix(_END)
                found.append((start, Measurement(name, "ms", (mark.t_ns - start) / _NS_PER_MS)))
    found.sort(key=lambda pair: pair[0])
    return [measurement for _, measurement in found]


def stats(values: Sequence[float]) -> Stats:
    """The count, median and nearest-rank 95th percentile of `values`.

    Raises:
        ValueError: `values` is empty.
    """
    if not values:
        msg = "no values to summarize"
        raise ValueError(msg)
    ordered = sorted(values)
    rank = math.ceil(0.95 * len(ordered))
    return Stats(n=len(ordered), median=statistics.median(ordered), p95=ordered[rank - 1])
