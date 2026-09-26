import pytest

from mscts.measure import Measurement, Stats, measurements, stats
from mscts.transcript import Mark, Transcript


def _transcript(*marks: tuple[int, str]) -> Transcript:
    transcript = Transcript(scenario_id="status/ping", server="vanilla")
    transcript.marks.extend(Mark(t_ns=t_ns, label=label) for t_ns, label in marks)
    return transcript


def test_a_span_is_a_measurement_in_milliseconds() -> None:
    transcript = _transcript((1_000_000, "status.rtt:start"), (3_500_000, "status.rtt:end"))

    assert measurements(transcript) == [Measurement(name="status.rtt", unit="ms", value=2.5)]


def test_an_unmatched_start_yields_nothing() -> None:
    transcript = _transcript((0, "status.rtt:start"), (5, "other:end"))

    assert measurements(transcript) == []


def test_spans_are_paired_in_order_and_listed_by_start() -> None:
    transcript = _transcript(
        (0, "a:start"),
        (1_000_000, "b:start"),
        (2_000_000, "a:end"),
        (4_000_000, "a:start"),
        (5_000_000, "b:end"),
        (9_000_000, "a:end"),
    )

    assert measurements(transcript) == [
        Measurement("a", "ms", 2.0),
        Measurement("b", "ms", 4.0),
        Measurement("a", "ms", 5.0),
    ]


def test_a_mark_that_is_not_a_span_end_is_ignored() -> None:
    transcript = _transcript((0, "joined"), (1, "x:end"), (2, "x:start"), (2_000_002, "x:end"))

    assert measurements(transcript) == [Measurement("x", "ms", 2.0)]


def test_stats_are_the_median_the_nearest_rank_p95_and_the_count() -> None:
    assert stats([3.0, 1.0, 2.0]) == Stats(n=3, median=2.0, p95=3.0)
    assert stats([4.0, 1.0, 3.0, 2.0]) == Stats(n=4, median=2.5, p95=4.0)
    assert stats(list(map(float, range(1, 101)))).p95 == 95.0


def test_stats_of_nothing_is_refused() -> None:
    with pytest.raises(ValueError, match="no values"):
        stats([])
