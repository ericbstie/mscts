"""What the Self-check tier (`tests/selfcheck/`) is made of: a test per registered Group.

`tests/selfcheck/conftest.py` imports `pytest_generate_tests` from here, so a test that takes a
`group_id` runs once for each Group in `GROUPS`, with the Group's id as its test id. Nothing
else needs to be written when a Group is registered (#84). Each case carries its Group's time
limit (`time_limit_s`): 90 s a play, and more for the few Groups in `SLOW_PLAY_LIMIT_S` (#423).
"""

import dataclasses
import os
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from pathlib import Path

import pytest
from _pytest.mark import ParameterSet

import mscts.groups  # noqa: F401 - registers the shipped Groups
from mscts.compare import Outcome, Verdict
from mscts.group import GROUPS, Group, GroupKind
from mscts.run import RunResult
from mscts.spec import ServerSpec
from support.verdict_text import describe_mismatches

REPEAT_VAR = "MSCTS_SELFCHECK_REPEAT"
DEFAULT_REPEAT = 3
"""How many times a Group is played by default; a Group's PR runs 20 once, by hand."""
PLAY_LIMIT_S = 90
"""Seconds a play of a Group may take, unless `SLOW_PLAY_LIMIT_S` lists it (#182).

It was twice the 45 s a play of `blocks/clone`, then the slowest Group; the Groups that have
since outgrown it are listed."""
MIN_LIMIT_S = 900
"""The least a Self-check's time limit is, whatever the repeat: two boots and a few plays."""
SLOW_PLAY_LIMIT_S: Mapping[str, int] = {
    # 96 s a play on main 55ee515 (3 plays: 287.3 s; load average 5.3 when it queued, 3.7 after),
    # twice that (#436).
    "player/fall": 192,
    # 112 s a play on main (3 plays: 336.6 s; load average 0.76 before, 1.18 after), twice that
    # for headroom, as the default has (#423).
    "player/starvation": 225,
    # A play of a glitch Group plays redstone/piston-push and redstone/sticky first. 20 plays on
    # the #42 branch (d82c86e): 1501.8 s, 1596.4 s and 1382.8 s, so 75, 80 and 69 s a play (load
    # average 0.3 to 0.7), twice that.
    "glitches/bedrock-breaking": 150,
    "glitches/tnt-duplication": 160,
    "glitches/rail-carpet-duplication": 140,
}
"""Seconds a play may take, for the Groups that need more than `PLAY_LIMIT_S`. A Group goes in
with its play time measured on main (`mise run test:selfcheck` with `--durations`) and the load
average, and twice that as its limit."""


def repeat_from(environ: Mapping[str, str]) -> int:
    """How many times to play each Group: `MSCTS_SELFCHECK_REPEAT` in `environ`, else 3.

    Raises:
        ValueError: The variable is set to anything but a whole number of at least 1.
    """
    text = environ.get(REPEAT_VAR, "")
    if not text:
        return DEFAULT_REPEAT
    try:
        repeat = int(text)
    except ValueError:
        repeat = 0
    if repeat < 1:
        msg = f"{REPEAT_VAR} is {text!r}: it must be a whole number of at least 1"
        raise ValueError(msg)
    return repeat


def time_limit_s(group_id: str, repeat: int) -> int:
    """Seconds pytest lets `group_id`'s Self-check run when each play is played `repeat` times."""
    return max(MIN_LIMIT_S, SLOW_PLAY_LIMIT_S.get(group_id, PLAY_LIMIT_S) * repeat)


def may_replay(groups: Sequence[Group], verdicts: Sequence[Verdict]) -> bool:
    """Whether `verdicts` is nothing but a statistical Group's rejection by chance.

    So its Self-check is worth playing once more (#388): every Verdict that is not `match`
    is a `mismatch` of a Group in `groups` that is statistical, whose Divergences are all
    `distribution` ones, and there is at least one. An `error`, a `failed` Divergence or
    any other kind of Group fails at once.
    """
    statistical = {group.id for group in groups if group.kind is GroupKind.STATISTICAL}
    unmatched = [verdict for verdict in verdicts if verdict.outcome is not Outcome.MATCH]
    return bool(unmatched) and all(_by_chance(verdict, statistical) for verdict in unmatched)


def _by_chance(verdict: Verdict, statistical: Collection[str]) -> bool:
    return (
        verdict.group_id in statistical
        and verdict.outcome is Outcome.MISMATCH
        and bool(verdict.divergences)
        and all(divergence.kind == "distribution" for divergence in verdict.divergences)
    )


type PlayOnce = Callable[[Path], Awaitable[RunResult]]
"""Plays the Groups once, in the folder it is given, and gives the Run."""


async def play_and_replay(
    groups: Sequence[Group], play: PlayOnce, replay: PlayOnce, workdir: Path
) -> tuple[RunResult, ...]:
    """Play `groups` with `play`, and with `replay` too if that was a chance rejection.

    The plays are `first` and `replay` under `workdir`. `replay` is called only when
    `may_replay` says the first was nothing but a statistical Group's rejection by chance
    (#388), so what is given back is one Run, or two. It is a play of its own, not `play`
    again: the caller gives it Instances that carry nothing over from the first.
    """
    first = await play(workdir / "first")
    if not may_replay(groups, first.verdicts):
        return (first,)
    return (first, await replay(workdir / "replay"))


def describe_failure(plays: Sequence[RunResult], where: Path) -> str:
    """Why the Self-check failed, or "" if its last play matched.

    A replayed Self-check fails only if the replay did not match either, so the text names
    the replay and the play it repeated, each as `describe_mismatches` writes it, with their
    timelines in `first` and `replay` under `where`.
    """
    last = plays[-1]
    if all(verdict.outcome is Outcome.MATCH for verdict in last.verdicts):
        return ""
    if len(plays) == 1:
        return describe_mismatches(last, where)
    first = describe_mismatches(plays[0], where / "first")
    replay = describe_mismatches(last, where / "replay")
    heading = "Played again after the first play was rejected."
    return f"{heading}\nFirst play:\n{first}\nReplay:\n{replay}"


def needs_instances_of_their_own(groups: Sequence[Group], pair_spec: ServerSpec) -> bool:
    """Whether a Group of `groups` changes the ServerSpec the shared pair was booted with.

    A Run can only play such a Group on Instances it launches itself (`run` refuses an
    Attached side of another ServerSpec). The Endpoint is no part of the ServerSpec here.
    """
    return any(
        dataclasses.replace(group.spec(pair_spec), host=pair_spec.host, port=pair_spec.port)
        != pair_spec
        for group in groups
    )


def selfcheck_params(groups: Mapping[str, Group]) -> list[ParameterSet]:
    """One `group_id` per Group in `groups`, a statistical Group's marked `statistical`.

    So the unit tier, which leaves the `statistical` mark out, never plays one, and
    `mise run test:statistical` does.
    """
    return [
        pytest.param(group_id, marks=pytest.mark.statistical)
        if group.kind is GroupKind.STATISTICAL
        else pytest.param(group_id)
        for group_id, group in groups.items()
    ]


def with_time_limits(params: Sequence[ParameterSet], repeat: int) -> list[ParameterSet]:
    """`params` (each a `group_id`) with the pytest timeout of its Group at `repeat` plays.

    The limit is a mark on each case: pytest-timeout reads the closest `timeout` mark when a
    test starts, so a module-wide mark cannot give one Group more time than the rest.
    """
    return [
        pytest.param(
            *param.values,
            id=param.id,
            marks=[*param.marks, pytest.mark.timeout(time_limit_s(str(param.values[0]), repeat))],
        )
        for param in params
    ]


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Give every test that takes a `group_id` one run per registered Group, with its limit."""
    if "group_id" in metafunc.fixturenames:
        cases = with_time_limits(selfcheck_params(GROUPS), repeat_from(os.environ))
        metafunc.parametrize("group_id", cases)
