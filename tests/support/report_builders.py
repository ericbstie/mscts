"""Divergences, Verdicts, results and Reports for the tests of how a Run is reported."""

from dataclasses import replace

from mscts.compare import Divergence, Observability, Outcome, Verdict
from mscts.report import Report
from mscts.run import GroupResult, SideSummary
from mscts.target import TARGET


def divergent_field(name: str, *, traffic: bool = False) -> Divergence:
    return Divergence(
        bot="status",
        index=0,
        kind="field",
        packet="minecraft:status_response",
        path=name,
        reference="reference value",
        candidate="candidate value",
        test_case=name,
        observability=Observability.NETWORK_TRAFFIC if traffic else Observability.GAMEPLAY,
    )


def report_verdict(*divergences: Divergence, group_id: str = "status/basic") -> Verdict:
    """A Verdict as compare makes it: a network traffic Divergence's test case is not listed.

    So such a test case is one no compared pair names (#330). `listed_verdict` lists it too.
    """
    gameplay = {d.test_case for d in divergences if d.observability is Observability.GAMEPLAY}
    return Verdict(
        group_id,
        Outcome.MISMATCH if divergences else Outcome.MATCH,
        divergences,
        test_cases=tuple(sorted(gameplay - {""})),
    )


def listed_verdict(*divergences: Divergence, group_id: str = "status/basic") -> Verdict:
    """A Verdict that lists each Divergence's test case: compared as well, or before #330."""
    names = {d.test_case for d in divergences} - {""}
    return replace(report_verdict(*divergences, group_id=group_id), test_cases=tuple(sorted(names)))


def group_result(*verdicts: Verdict) -> GroupResult:
    return GroupResult(verdicts[0].group_id, verdicts, (), ())


def report_of(*results: GroupResult, elapsed_s: float = 41.0) -> Report:
    return Report(
        TARGET,
        SideSummary("vanilla", "26.3", ()),
        SideSummary("pumpkin", "Pumpkin 26.2", ()),
        results,
        ("--out is not implemented yet",),
        elapsed_s,
    )
