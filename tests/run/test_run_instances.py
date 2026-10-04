import dataclasses
from collections.abc import Callable
from pathlib import Path

import pytest

from mscts import run as run_module
from mscts.compare import Outcome, Verdict
from mscts.group import Group, GroupContext, GroupKind
from mscts.groups import status
from mscts.net import Endpoint
from mscts.report import GroupLine, LineResult, Totals, report_lines, totals
from mscts.run import GroupResult, Server, run, run_results
from mscts.spec import ServerSpec
from tests.run.fakes import FakeAdapter
from tests.test_report import _report

BASIC = Group(id="status/basic", run=status.basic)
PING = Group(id="status/ping", run=status.ping, requires=("status/basic",))
AFTER_PING = Group(id="test/after-ping", run=status.ping, requires=("status/ping",))

type MakeServer = Callable[..., Server]


def _adapter(server: Server) -> FakeAdapter:
    assert isinstance(server.adapter, FakeAdapter)
    return server.adapter


@pytest.mark.asyncio
async def test_a_run_against_two_equal_servers_matches(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    verdicts = await run(
        [BASIC, PING], fake_server("one"), fake_server("two"), workdir=tmp_path / "run"
    )

    assert [(v.group_id, v.outcome) for v in verdicts] == [
        ("status/basic", Outcome.MATCH),
        ("status/ping", Outcome.MATCH),
    ]


@pytest.mark.asyncio
async def test_each_side_runs_on_its_own_free_endpoint(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    reference, candidate = fake_server("one"), fake_server("two")

    await run([BASIC], reference, candidate, workdir=tmp_path / "run")

    [one], [two] = _adapter(reference).prepared, _adapter(candidate).prepared
    assert one.host != two.host
    assert one == ServerSpec(host=one.host, port=one.port)


@pytest.mark.asyncio
async def test_a_candidate_that_differs_is_a_mismatch_and_blocks_what_requires_it(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    candidate = fake_server("two", description="not vanilla")

    basic, ping = await run([BASIC, PING], fake_server("one"), candidate, workdir=tmp_path / "run")

    assert basic.outcome is Outcome.MISMATCH
    assert [d.candidate for d in basic.divergences] == ["not vanilla"]
    assert ping.outcome is Outcome.BLOCKED
    assert ping.detail == "prerequisite status/basic was mismatch"


@pytest.mark.asyncio
async def test_a_group_blocked_by_the_candidate_fails_each_test_case_of_the_references_play(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    # #285, audit M1: sending every value of PING wrong fails each test case of the
    # Reference's play of it, so failing its prerequisite must fail each of them too.
    candidate = fake_server("two", description="not vanilla")

    _, ping = await run([BASIC, PING], fake_server("one"), candidate, workdir=tmp_path / "run")
    own = await _test_cases(PING, fake_server, tmp_path / "own")

    assert ping.test_cases == own
    lines = report_lines(_report(GroupResult(PING.id, (ping,), (), ())))
    reason = "Not tested: prerequisite status/basic was mismatch"
    assert lines[-1] == GroupLine(PING.id, LineResult.NOT_TESTED, reason)
    assert totals(lines) == Totals(passed=0, failed=len(own) + 1, not_tested=1, errors=0)


@pytest.mark.asyncio
async def test_a_group_blocked_by_a_blocked_group_still_plays_the_reference(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    candidate = fake_server("two", description="not vanilla")

    *_, after = await run(
        [BASIC, PING, AFTER_PING], fake_server("one"), candidate, workdir=tmp_path / "run"
    )

    assert after.outcome is Outcome.BLOCKED
    assert after.detail == "prerequisite status/ping was blocked"
    assert after.test_cases == await _test_cases(AFTER_PING, fake_server, tmp_path / "own")


@pytest.mark.asyncio
async def test_a_group_whose_prerequisite_is_an_error_is_played_on_neither_side(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    # Audit L2: an `error` is the Reference's or mscts's; what depends on it is not played.
    async def fails(context: GroupContext) -> None:
        del context
        msg = "vanilla stopped"
        raise RuntimeError(msg)

    broken = Group(id="status/basic", run=fails)

    result = await run_results(
        [broken, PING, AFTER_PING], fake_server("one"), fake_server("two"), workdir=tmp_path
    )

    _, ping, after = result.results
    assert [verdict.test_cases for verdict in (*ping.verdicts, *after.verdicts)] == [(), ()]
    assert ping.elapsed_s == after.elapsed_s == (0.0,), "neither side was played"


@pytest.mark.asyncio
async def test_an_identical_candidate_scores_full_marks_when_vanilla_fails_a_prerequisite(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    # Audit L2, review B: both sides raise on status/basic; that is vanilla's or mscts's
    # fault, so neither it nor what requires it is scored against the Candidate.
    async def fails(context: GroupContext) -> None:
        del context
        msg = "both flake"
        raise RuntimeError(msg)

    broken = Group(id="status/basic", run=fails)
    passing = Group(id="test/passing", run=status.basic)

    result = await run_results(
        [broken, PING, AFTER_PING, passing],
        fake_server("one"),
        fake_server("two"),
        workdir=tmp_path,
    )

    _, ping, after, _ = result.results
    assert ping.verdicts == (
        Verdict(PING.id, Outcome.ERROR, detail="prerequisite status/basic was error"),
    )
    assert after.verdicts[0].detail == "prerequisite status/ping was error"
    counted = totals(report_lines(_report(*result.results)))
    assert (counted.failed, counted.errors, counted.score) == (0, 3, 1.0)


@pytest.mark.asyncio
async def test_a_group_whose_prerequisite_was_not_run_is_played_on_neither_side(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    result = await run_results([PING], fake_server("one"), fake_server("two"), workdir=tmp_path)

    [ping] = result.results
    assert ping.verdicts == (
        Verdict(PING.id, Outcome.BLOCKED, detail="prerequisite status/basic was not run"),
    )
    assert ping.elapsed_s == (0.0,)


@pytest.mark.asyncio
async def test_a_reference_error_in_one_repetition_fails_no_test_case_of_what_requires_it(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    # Review A #289: in repetition 2 vanilla raises on the prerequisite, so PING is played
    # on neither side; its test cases from repetition 1, which matched, still pass.
    plays: list[Endpoint] = []

    async def flaky(context: GroupContext) -> None:
        plays.append(context.endpoint)
        if context.endpoint == plays[0] and plays.count(plays[0]) == 2:  # the Reference
            msg = "vanilla flaked"
            raise RuntimeError(msg)
        await status.basic(context)

    basic = Group(id=BASIC.id, run=flaky)

    result = await run_results(
        [basic, PING], fake_server("one"), fake_server("two"), workdir=tmp_path, repeat=2
    )

    flaked, ping = result.results
    assert [verdict.outcome for verdict in flaked.verdicts] == [Outcome.MATCH, Outcome.ERROR]
    assert [verdict.outcome for verdict in ping.verdicts] == [Outcome.MATCH, Outcome.ERROR]
    cases = [line for line in report_lines(_report(ping)) if not isinstance(line, GroupLine)]
    assert cases
    assert {line.result for line in cases} == {LineResult.PASS}


@pytest.mark.asyncio
async def test_only_the_reference_is_waited_on_for_a_group_blocked_by_the_candidate(
    monkeypatch: pytest.MonkeyPatch, fake_server: MakeServer, tmp_path: Path
) -> None:
    # Whatever the Candidate still has online, it is not played: waiting on it would
    # only replace the reason with another.
    waited: list[int] = []

    async def settled(group: Group, reference: Endpoint, candidate: Endpoint | None) -> None:
        del group, reference
        waited.append(1 if candidate is None else 2)

    monkeypatch.setattr(run_module, "_unsettled", settled)
    candidate = fake_server("two", description="not vanilla")

    await run([BASIC, PING], fake_server("one"), candidate, workdir=tmp_path)

    assert waited == [2, 1]


async def _test_cases(group: Group, fake_server: MakeServer, workdir: Path) -> tuple[str, ...]:
    """The test cases of `group` played on two fakes that agree, its prerequisites first."""
    groups = [BASIC, PING, AFTER_PING][: [BASIC, PING, AFTER_PING].index(group) + 1]
    verdicts = await run(groups, fake_server("one"), fake_server("two"), workdir=workdir)
    assert verdicts[-1].outcome is Outcome.MATCH, verdicts
    assert verdicts[-1].test_cases, "the Group must have test cases for this to show anything"
    return verdicts[-1].test_cases


@pytest.mark.asyncio
async def test_repetitions_reuse_the_instances(fake_server: MakeServer, tmp_path: Path) -> None:
    reference, candidate = fake_server("one"), fake_server("two")

    verdicts = await run([BASIC, PING], reference, candidate, workdir=tmp_path / "run", repeat=3)

    assert [v.group_id for v in verdicts] == ["status/basic", "status/ping"] * 3
    assert {v.outcome for v in verdicts} == {Outcome.MATCH}
    assert len(_adapter(reference).prepared) == len(_adapter(candidate).prepared) == 1


@pytest.mark.asyncio
async def test_a_group_with_its_own_spec_gets_instances_of_its_own(
    fake_server: MakeServer, tmp_path: Path
) -> None:
    reference, candidate = fake_server("one"), fake_server("two")

    def other_motd(spec: ServerSpec) -> ServerSpec:
        return dataclasses.replace(spec, motd="other")

    custom = Group(id="test/custom", run=status.basic, spec=other_motd)

    verdicts = await run([BASIC, custom, PING], reference, candidate, workdir=tmp_path / "run")

    assert {v.outcome for v in verdicts} == {Outcome.MATCH}
    assert [spec.motd for spec in _adapter(reference).prepared] == ["mscts", "other"]
    assert [spec.motd for spec in _adapter(candidate).prepared] == ["mscts", "other"]


@pytest.mark.asyncio
async def test_a_statistical_group_cannot_run_yet(fake_server: MakeServer, tmp_path: Path) -> None:
    group = Group(id="test/kind", run=status.basic, kind=GroupKind.STATISTICAL)
    reference = fake_server("one")

    with pytest.raises(
        NotImplementedError,
        match="test/kind is statistical: only exact and tick-exact Groups can run",
    ):
        await run([group], reference, fake_server("two"), workdir=tmp_path / "run")

    assert _adapter(reference).prepared == []


@pytest.mark.asyncio
async def test_a_tick_exact_group_runs(fake_server: MakeServer, tmp_path: Path) -> None:
    group = Group(id="test/kind", run=status.basic, kind=GroupKind.TICK_EXACT)

    verdicts = await run([group], fake_server("one"), fake_server("two"), workdir=tmp_path / "run")

    assert [verdict.outcome for verdict in verdicts] == [Outcome.MATCH]


@pytest.mark.asyncio
async def test_a_group_listed_twice_is_refused(fake_server: MakeServer, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="status/basic"):
        await run([BASIC, BASIC], fake_server("one"), fake_server("two"), workdir=tmp_path)
