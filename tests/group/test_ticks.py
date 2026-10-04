"""Tick-exact Groups: `freeze` and `step` against a fake server, and the Marks they leave."""

import pytest
from support.probe import REPEATER_STEPPED

from mscts.codec.packets import Direction
from mscts.compare import TICK_MARK, Outcome
from mscts.group import CommandMissing, Group, GroupContext, GroupKind
from mscts.run import GroupError, judge, run_group
from mscts.transcript import Transcript
from tests.group.test_control import (
    AWARD_STATS,
    CODEC,
    MARKER,
    ControlServer,
    commands_sent,
    playing,
    tree,
)
from tests.net.fakes import serve

CONTROL = "control"


def steps(seen: list[object]) -> list[object]:
    """The commands Control sent, but its markers."""
    return [command for command in seen if not str(command).startswith(MARKER)]


def tick_marks(transcript: Transcript) -> list[str]:
    return [mark.label for mark in transcript.marks if mark.label.startswith(TICK_MARK)]


async def joined(context: GroupContext, name: str = "alice") -> None:
    bot = await context.bot(name)
    await bot.join()


@pytest.mark.asyncio
async def test_step_runs_one_tick_step_through_control_for_each_tick() -> None:
    server = ControlServer()
    transcript = Transcript(group_id="test/ticks", server="fake")
    async with playing(server, transcript) as context:
        await context.freeze()
        await context.step(3)
        sent = steps(commands_sent(server.seen))

    assert sent == ["tick freeze", "tick step 1", "tick step 1", "tick step 1"]


@pytest.mark.asyncio
async def test_each_step_marks_its_tick_for_every_bot_after_its_barrier() -> None:
    transcript = Transcript(group_id="test/ticks", server="fake")
    async with playing(ControlServer(), transcript) as context:
        await joined(context)
        await context.freeze()
        await context.step(2)

    assert tick_marks(transcript) == [
        *(f"tick:1 {name}" for name in ("alice", CONTROL)),
        "tick:1",
        *(f"tick:2 {name}" for name in ("alice", CONTROL)),
        "tick:2",
    ]
    answers = [
        event.t_ns
        for event in transcript.events
        if event.bot == "alice"
        and event.packet.name == AWARD_STATS
        and event.packet.direction is Direction.CLIENTBOUND
    ]
    for mark in transcript.marks:
        if mark.label.startswith(TICK_MARK) and mark.label.endswith(" alice"):
            # A packet stamped at a Mark's time is after it: the answer is inside the tick.
            assert mark.t_ns - 1 in answers, (mark, answers)


@pytest.mark.asyncio
async def test_ticks_count_on_from_the_freeze_across_steps() -> None:
    transcript = Transcript(group_id="test/ticks", server="fake")
    async with playing(ControlServer(), transcript) as context:
        await context.freeze()
        await context.step()
        await context.step(2)

    assert [label for label in tick_marks(transcript) if " " not in label] == [
        "tick:1",
        "tick:2",
        "tick:3",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("ticks", [0, -1])
async def test_step_refuses_fewer_than_one_tick(ticks: int) -> None:
    server = ControlServer()
    transcript = Transcript(group_id="test/ticks", server="fake")
    async with playing(server, transcript) as context:
        await context.freeze()
        with pytest.raises(ValueError, match="at least one tick"):
            await context.step(ticks)

    assert "tick step 1" not in commands_sent(server.seen)


@pytest.mark.asyncio
async def test_step_refuses_a_world_the_group_has_not_frozen() -> None:
    server = ControlServer()
    transcript = Transcript(group_id="test/ticks", server="fake")
    async with playing(server, transcript) as context:
        with pytest.raises(ValueError, match="freeze"):
            await context.step()

    assert commands_sent(server.seen) == []


@pytest.mark.asyncio
async def test_freeze_refuses_a_world_the_group_has_frozen_already() -> None:
    transcript = Transcript(group_id="test/ticks", server="fake")
    async with playing(ControlServer(), transcript) as context:
        await context.freeze()
        with pytest.raises(ValueError, match="frozen the world already"):
            await context.freeze()


@pytest.mark.asyncio
async def test_the_world_is_unfrozen_when_the_group_ends_however_it_ends() -> None:
    server = ControlServer()
    transcript = Transcript(group_id="test/ticks", server="fake")

    async def failing() -> None:
        async with playing(server, transcript) as context:
            await context.freeze()
            await context.step()
            msg = "the script failed"
            raise RuntimeError(msg)

    with pytest.raises(RuntimeError, match="the script failed"):
        await failing()

    assert steps(commands_sent(server.seen))[-1] == "tick unfreeze"


@pytest.mark.asyncio
async def test_a_group_that_never_froze_the_world_does_not_unfreeze_it() -> None:
    server = ControlServer()
    transcript = Transcript(group_id="test/ticks", server="fake")
    async with playing(server, transcript) as context:
        await context.control.run("setblock 1 -60 1 minecraft:stone")

    assert "tick unfreeze" not in commands_sent(server.seen)


async def _probe(context: GroupContext) -> None:
    await joined(context)
    await context.freeze()
    async with context.observe():
        await context.step(2)


PROBE = Group(id="test/ticks", run=_probe, kind=GroupKind.TICK_EXACT)


async def played(server: ControlServer) -> Transcript | GroupError:
    async with serve(CODEC, server) as endpoint:
        try:
            return await run_group(PROBE, endpoint, server="fake", timeout_s=0.5)
        except GroupError as error:
            return error


@pytest.mark.asyncio
async def test_a_candidate_without_tick_is_blocked_needing_it() -> None:
    reference = await played(ControlServer())
    candidate = await played(ControlServer(commands=tree("setblock", "tellraw")))

    assert isinstance(candidate, GroupError)
    assert isinstance(candidate.__cause__, CommandMissing)
    verdict = judge(PROBE, reference, candidate)
    assert verdict.outcome is Outcome.BLOCKED, verdict
    assert verdict.detail == "needs /tick"


@pytest.mark.asyncio
async def test_a_candidate_that_never_finishes_a_step_fails() -> None:
    def hang_after_the_first_step(command: str) -> None:
        if command == "tick step 1":
            hanging.answers_markers = False

    reference = await played(ControlServer())
    hanging = ControlServer(on_command=hang_after_the_first_step)
    candidate = await played(hanging)

    assert isinstance(candidate, GroupError)
    assert isinstance(candidate.__cause__, TimeoutError)
    verdict = judge(PROBE, reference, candidate)
    assert verdict.outcome is Outcome.MISMATCH, verdict
    assert verdict.divergences[0].kind == "failed", verdict


@pytest.mark.asyncio
async def test_a_server_that_does_not_unfreeze_fails_the_group() -> None:
    # Review of #223, LOW 2: a world left frozen would spoil every later Group on the
    # Instance, so a failed unfreeze fails this one: the Reference's error, a Candidate's
    # failure.
    def hang_on_unfreeze(command: str) -> None:
        if command == "tick unfreeze":
            stuck.answers_markers = False

    stuck = ControlServer(on_command=hang_on_unfreeze)
    failed = await played(stuck)

    assert isinstance(failed, GroupError), failed
    assert isinstance(failed.__cause__, TimeoutError)
    reference = await played(ControlServer())
    assert judge(PROBE, failed, reference).outcome is Outcome.ERROR
    assert steps(commands_sent(stuck.seen)).count("tick unfreeze") == 1


PROBE_TREE = tree("tp", "tick", "gamerule", "setblock", "fill", "tellraw")
RANDOM_TICKS_OFF, RANDOM_TICKS_ON = "gamerule random_tick_speed 0", "gamerule random_tick_speed 3"


@pytest.mark.asyncio
async def test_the_repeater_probe_steps_with_random_ticks_off() -> None:
    # #272: a stepped tick runs random ticks, and the grass under the redstone block
    # turned to dirt on one Instance only.
    server = ControlServer(commands=PROBE_TREE)
    transcript = Transcript(group_id=REPEATER_STEPPED.id, server="fake")
    async with playing(server, transcript) as context:
        await REPEATER_STEPPED.run(context)
        await context.end()
    sent = steps(commands_sent(server.seen))

    assert sent.index("tick freeze") < sent.index(RANDOM_TICKS_OFF) < sent.index("tick step 1")
    assert sent[-3:] == [
        "fill 1 -60 4 5 -60 4 minecraft:air",
        RANDOM_TICKS_ON,
        "tick unfreeze",
    ]


@pytest.mark.asyncio
async def test_the_repeater_probe_turns_random_ticks_back_on_when_it_fails() -> None:
    def hang_on_the_first_step(command: str) -> None:
        if command == "tick step 1":
            server.answers_markers = False

    server = ControlServer(commands=PROBE_TREE, on_command=hang_on_the_first_step)
    transcript = Transcript(group_id=REPEATER_STEPPED.id, server="fake")

    async def failing() -> None:
        async with playing(server, transcript, timeout_s=0.5) as context:
            await REPEATER_STEPPED.run(context)

    with pytest.raises(TimeoutError):
        await failing()

    assert RANDOM_TICKS_ON in steps(commands_sent(server.seen))
