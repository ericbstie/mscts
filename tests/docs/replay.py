"""Replay the recorded Report input without servers or Java (#14)."""

import json
from pathlib import Path

from mscts.compare import ABSENT, Divergence, Observability, Outcome, Verdict
from mscts.measure import Measurement
from mscts.report import Report
from mscts.run import GroupResult, SideSummary
from mscts.target import Target


def report_from_sample(path: Path) -> Report:
    """Reconstruct the Report captured alongside a sample's stdout."""
    data = json.loads(path.read_text())
    results = []
    for result in data["results"]:
        verdicts = []
        for verdict in result["verdicts"]:
            divergences = [
                Divergence(
                    bot=divergence["bot"],
                    index=divergence["index"],
                    kind=divergence["kind"],
                    packet=divergence["packet"],
                    path=divergence["path"],
                    reference=ABSENT
                    if divergence["reference"] == {"absent": True}
                    else divergence["reference"],
                    candidate=ABSENT
                    if divergence["candidate"] == {"absent": True}
                    else divergence["candidate"],
                    test_case=divergence["test_case"],
                    observability=Observability(divergence["observability"]),
                )
                for divergence in verdict["divergences"]
            ]
            verdicts.append(
                Verdict(
                    verdict["group_id"],
                    Outcome(verdict["outcome"]),
                    tuple(divergences),
                    verdict["detail"],
                    tuple(verdict["test_cases"]),
                )
            )
        results.append(
            GroupResult(
                result["group_id"],
                tuple(verdicts),
                tuple(tuple(Measurement(**m) for m in run) for run in result["reference"]),
                tuple(tuple(Measurement(**m) for m in run) for run in result["candidate"]),
                tuple(result.get("elapsed_s", ())),
            )
        )
    sides = [
        SideSummary(
            data[role]["name"],
            data[role]["version"],
            tuple(Measurement(**m) for m in data[role]["startup"]),
            data[role].get("installed_version"),
        )
        for role in ("reference", "candidate")
    ]
    return Report(
        Target(**data["target"]),
        sides[0],
        sides[1],
        tuple(results),
        tuple(data["notes"]),
        data["elapsed_s"],
    )
