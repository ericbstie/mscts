"""The Verdict rule (audit H3): a failure the Candidate caused is a `mismatch`, never `error`.

Each Candidate failure mode is a fake server the Group is played against, as the
Candidate; the Reference side is a well-behaved fake. `error` stays for the harness,
and for the Reference itself failing.
"""

import contextlib
import dataclasses
import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

import mscts.run as run_module
from mscts.codec.packets import Codec, Packet
from mscts.codec.wire import Writer
from mscts.compare import Divergence, Mask, Outcome, Verdict, compare
from mscts.group import GROUPS, CommandMissing, Group, GroupContext
from mscts.groups import status
from mscts.net import Endpoint, ProtocolError
from mscts.report import report_lines, totals
from mscts.run import GroupError, Server, judge, run_group, run_results
from mscts.settle import PlayersStillOnline
from mscts.target import TARGET
from mscts.transcript import Transcript
from tests.compare.build import divergence, packet, transcript
from tests.net.fakes import VANILLA_STATUS, Handler, Peer, free_port, serve, status_server
from tests.test_report import _report, _result

BASIC = Group(id="status/basic", run=status.basic)
TIMEOUT_S = 0.2


async def _play(group: Group, handler: Handler | None) -> Transcript | GroupError:
    """Play `group` against a fake running `handler`, or against a closed port if None."""
    if handler is None:
        return await _attempt(group, Endpoint("127.0.0.1", free_port()))
    async with serve(Codec.for_target(TARGET), handler) as endpoint:
        return await _attempt(group, endpoint)


async def _attempt(group: Group, endpoint: Endpoint) -> Transcript | GroupError:
    try:
        return await run_group(group, endpoint, server="fake", timeout_s=TIMEOUT_S)
    except GroupError as error:  # caught inside serve, which would replace its cause
        return error


def _status_json() -> str:
    return json.dumps(VANILLA_STATUS)


async def _trailing_byte(peer: Peer) -> None:
    await peer.recv()  # the intention
    await peer.recv()  # status_request
    text = Writer().string(_status_json(), max_length=32767).to_bytes()
    await peer.write(peer.raw_frame("minecraft:status_response", text + b"\x00"))
    await peer.eof()


async def _not_an_object(peer: Peer) -> None:
    await peer.recv()
    await peer.recv()
    await peer.send("minecraft:status_response", json_response="[]")
    await peer.eof()


async def _silent(peer: Peer) -> None:
    await peer.recv()
    await peer.recv()
    await peer.eof()


async def _closes(peer: Peer) -> None:
    await peer.recv()
    await peer.recv()


@dataclass(frozen=True)
class Mode:
    handler: Handler | None
    failure: str


MODES = {
    "undecodable frame": Mode(
        _trailing_byte,
        "CodecError: status clientbound minecraft:status_response: 1 unconsumed byte(s) remain",
    ),
    "protocol error": Mode(
        _not_an_object, "ProtocolError: status_response json_response is not a JSON object"
    ),
    "timeout": Mode(_silent, f"TimeoutError: no answer within {TIMEOUT_S} s"),
    "connection closed": Mode(_closes, "ConnectionClosedError: the server closed the connection"),
    "connection refused": Mode(None, "ConnectionRefusedError: "),
}


def _failed(description: str, bot: str = "status") -> Divergence:
    return divergence("failed", bot=bot, candidate=description)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES.values(), ids=MODES.keys())
async def test_a_candidate_failure_is_a_mismatch_that_says_what_happened(mode: Mode) -> None:
    reference = await _play(BASIC, status_server(_status_json(), []))
    candidate = await _play(BASIC, mode.handler)
    assert isinstance(candidate, GroupError)

    verdict = judge(BASIC, reference, candidate)

    assert verdict.outcome is Outcome.MISMATCH
    failed = verdict.divergences[0]
    assert failed == _failed(str(candidate))
    assert str(candidate).startswith(mode.failure)
    assert verdict.detail == f"the Candidate failed: {candidate}"
    # Each test case the Reference's play has is the Candidate's too, failed (#262).
    assert isinstance(reference, Transcript)
    own = compare(reference, reference, ()).test_cases
    assert len(own) > 1
    assert set(own) <= set(verdict.test_cases)
    assert verdict.test_cases == tuple(sorted(set(verdict.test_cases)))


@pytest.mark.asyncio
async def test_a_candidate_failure_against_a_reference_the_comparison_cannot_take_is_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = await _play(BASIC, status_server(_status_json(), []))
    candidate = await _play(BASIC, _silent)
    assert isinstance(reference, Transcript)
    assert isinstance(candidate, GroupError)
    real = run_module.compare

    def odd_reference(ref: Transcript, cand: Transcript, masks: Sequence[Mask]) -> Verdict:
        if cand is ref:
            msg = "the Reference alone"
            raise RuntimeError(msg)
        return real(ref, cand, masks)

    monkeypatch.setattr(run_module, "compare", odd_reference)

    verdict = judge(BASIC, reference, candidate)

    # As when the Comparison raises: the Reference's data or mscts is at fault (#239).
    detail = "the Comparison failed: RuntimeError: the Reference alone"
    assert verdict == Verdict("status/basic", Outcome.ERROR, detail=detail)


@pytest.mark.asyncio
async def test_the_undecodable_frame_is_a_divergence_showing_both_payloads() -> None:
    reference = await _play(BASIC, status_server(_status_json(), []))
    candidate = await _play(BASIC, _trailing_byte)
    assert isinstance(reference, Transcript)
    assert isinstance(candidate, GroupError)

    verdict = judge(BASIC, reference, candidate)

    # Kept from the Comparison: the packet's, and each field vanilla sent in it (#230).
    fields = compare(reference, reference, ()).test_cases
    assert verdict.test_cases == tuple(sorted({"status_response", *fields}))
    assert len(verdict.test_cases) > 1
    [_, payload] = verdict.divergences
    reference_payload = reference.events[-1].packet.payload
    assert payload == divergence(
        "field",
        bot="status",
        packet="minecraft:status_response",
        reference=reference_payload.hex(),
        candidate=(reference_payload + b"\x00").hex(),
        test_case="status_response",
    )


@pytest.mark.asyncio
async def test_a_candidate_failure_survives_a_mask_on_the_whole_packet() -> None:
    mask = Mask(packet="minecraft:status_response", path="*", reason="test only")
    masked = Group(id="status/basic", run=status.basic, masks=(mask,))
    reference = await _play(masked, status_server(_status_json(), []))
    candidate = await _play(masked, _trailing_byte)
    assert isinstance(candidate, GroupError)

    verdict = judge(masked, reference, candidate)

    assert verdict.outcome is Outcome.MISMATCH
    assert verdict.divergences == (_failed(str(candidate)),)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES.values(), ids=MODES.keys())
async def test_the_same_failure_on_the_reference_is_an_error(mode: Mode) -> None:
    reference = await _play(BASIC, mode.handler)
    candidate = await _play(BASIC, status_server(_status_json(), []))
    assert isinstance(reference, GroupError)

    verdict = judge(BASIC, reference, candidate)

    assert verdict == Verdict(
        "status/basic", Outcome.ERROR, detail=f"the Reference failed: {reference}"
    )


async def _two_bots(context: GroupContext) -> None:
    """A Bot that only connects, then one that asks for the status."""
    await context.bot("idle")
    asker = await context.bot("asker")
    await asker.status()


async def _not_a_bot(context: GroupContext) -> None:
    """The script itself raises a Candidate failure, out of no Bot."""
    await context.bot("status")
    msg = "raised by the script"
    raise ProtocolError(msg)


@dataclass(frozen=True)
class Raiser:
    script: Group
    bot: str


RAISERS = {
    "the bot that raised, not the first": Raiser(Group(id="test/two-bots", run=_two_bots), "asker"),
    "no bot: the script raised": Raiser(Group(id="test/not-a-bot", run=_not_a_bot), ""),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("raiser", RAISERS.values(), ids=RAISERS.keys())
async def test_the_failed_divergence_names_the_bot_the_failure_came_out_of(raiser: Raiser) -> None:
    group = raiser.script
    candidate = await _play(group, _mute)
    assert isinstance(candidate, GroupError)

    verdict = judge(group, Transcript(group.id, "vanilla"), candidate)

    assert verdict.outcome is Outcome.MISMATCH
    assert verdict.divergences[0] == _failed(str(candidate), raiser.bot)


async def _waits_in_vain(context: GroupContext) -> None:  # noqa: ARG001 - a Script
    """The Group waited with `until_no_player_online` after `control.leave()`, in vain."""
    raise PlayersStillOnline(1, ["control"], 2.0)


WAITS_IN_VAIN = Group(id="test/waits-in-vain", run=_waits_in_vain)
STILL_ONLINE = "PlayersStillOnline: 1 player still online after waiting 2 s: 'control'"


@pytest.mark.asyncio
async def test_a_group_raising_players_still_online_on_the_candidate_is_a_mismatch() -> None:
    candidate = await _play(WAITS_IN_VAIN, _mute)
    assert isinstance(candidate, GroupError)

    verdict = judge(WAITS_IN_VAIN, Transcript(WAITS_IN_VAIN.id, "vanilla"), candidate)

    assert verdict == Verdict(
        "test/waits-in-vain",
        Outcome.MISMATCH,
        divergences=(_failed(STILL_ONLINE, bot=""),),
        detail=f"the Candidate failed: {STILL_ONLINE}",
    )


@pytest.mark.asyncio
async def test_a_group_raising_players_still_online_on_the_reference_is_an_error() -> None:
    reference = await _play(WAITS_IN_VAIN, _mute)
    assert isinstance(reference, GroupError)

    verdict = judge(WAITS_IN_VAIN, reference, Transcript(WAITS_IN_VAIN.id, "pumpkin"))

    detail = f"the Reference failed: {STILL_ONLINE}"
    assert verdict == Verdict("test/waits-in-vain", Outcome.ERROR, detail=detail)


def test_a_comparison_that_raises_value_error_is_an_error_naming_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuses(*_: object) -> Verdict:
        msg = "a path the Comparison refuses"
        raise ValueError(msg)

    monkeypatch.setattr(run_module, "compare", refuses)

    verdict = judge(BASIC, Transcript(BASIC.id, "vanilla"), Transcript(BASIC.id, "pumpkin"))

    detail = "the Comparison failed: ValueError: a path the Comparison refuses"
    assert verdict == Verdict("status/basic", Outcome.ERROR, detail=detail)


def _raises(error: BaseException) -> Callable[..., Verdict]:
    """A `compare` that raises `error`."""

    def comparison(*_: object) -> Verdict:
        raise error

    return comparison


def test_a_comparison_that_raises_a_runtime_error_is_an_error_naming_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(run_module, "compare", _raises(RuntimeError("a Comparison bug")))

    verdict = judge(BASIC, Transcript(BASIC.id, "vanilla"), Transcript(BASIC.id, "pumpkin"))

    detail = "the Comparison failed: RuntimeError: a Comparison bug"
    assert verdict == Verdict("status/basic", Outcome.ERROR, detail=detail)


def test_an_interrupt_during_the_comparison_ends_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(run_module, "compare", _raises(KeyboardInterrupt()))

    with pytest.raises(KeyboardInterrupt):
        judge(BASIC, Transcript(BASIC.id, "vanilla"), Transcript(BASIC.id, "pumpkin"))


def test_a_comparison_that_raises_logs_its_traceback(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    error = OverflowError("int too big to convert")
    monkeypatch.setattr(run_module, "compare", _raises(error))

    with caplog.at_level(logging.WARNING, logger="mscts.run"):
        judge(BASIC, Transcript(BASIC.id, "vanilla"), Transcript(BASIC.id, "pumpkin"))

    record, alone = caplog.records
    assert record.getMessage() == "the Comparison of status/basic failed"
    assert record.exc_info is not None
    assert record.exc_info[1] is error
    # It raises on the Reference against itself too, so it is the harness's `error` (#239).
    assert alone.getMessage() == "the Comparison of status/basic fails on the Reference alone"


@pytest.mark.asyncio
async def test_a_comparison_that_raises_anything_else_is_that_groups_error_and_the_run_goes_on(
    fake_server: Callable[..., Server], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # #173's review: a Candidate's chunk made compare raise OverflowError, which ended the Run.
    real = run_module.compare

    def overflows_on_basic(reference: Transcript, candidate: Transcript, masks: object) -> Verdict:
        if reference.group_id == "status/basic":
            msg = "int too big to convert"
            raise OverflowError(msg)
        return real(reference, candidate, masks)  # ty: ignore[invalid-argument-type]

    monkeypatch.setattr(run_module, "compare", overflows_on_basic)
    groups = [GROUPS["status/basic"], GROUPS["status/ping"]]

    result = await run_results(
        groups, fake_server("vanilla"), fake_server("pumpkin"), workdir=tmp_path / "run"
    )

    basic, ping = result.verdicts
    detail = "the Comparison failed: OverflowError: int too big to convert"
    assert basic == Verdict("status/basic", Outcome.ERROR, detail=detail)
    assert ping.group_id == "status/ping"
    assert ping.outcome is not Outcome.ERROR, ping


async def _needs_tick(context: GroupContext) -> None:  # noqa: ARG001 - a Script
    """Control found no `tick` in the server's command tree."""
    root = "tick"
    raise CommandMissing(root)


NEEDS_TICK = Group(id="test/needs-tick", run=_needs_tick)


@pytest.mark.asyncio
async def test_a_command_the_candidate_does_not_have_fails_the_group_needing_it() -> None:
    candidate = await _play(NEEDS_TICK, None)
    assert isinstance(candidate, GroupError)

    verdict = judge(NEEDS_TICK, Transcript(NEEDS_TICK.id, "vanilla"), candidate)

    assert verdict == Verdict(
        "test/needs-tick",
        Outcome.MISMATCH,
        divergences=(_failed("requires /tick", bot=""),),
        detail="the Candidate failed: requires /tick",
    )


def _block(x: int, state: int) -> Packet:
    position = {"x": x, "y": -60, "z": 0}
    return packet("minecraft:block_update", fields={"pos": position, "state": state})


SETS_BLOCKS = transcript(*(("alice", _block(x, 1)) for x in range(4)), group_id=NEEDS_TICK.id)
"""The Reference's play of a Group of 4 test cases: 4 blocks set."""

EVERY_VALUE_WRONG = transcript(
    *(
        (
            "alice",
            packet("minecraft:block_update", fields={"pos": {"x": x, "y": 0, "z": 9}, "state": 7}),
        )
        for x in range(100, 104)
    ),
    server="pumpkin",
    group_id=NEEDS_TICK.id,
)
"""The Candidate's play of it, with every value wrong."""

PASSING = Group(id="test/passing", run=_needs_tick)
"""A Group the Candidate passes, played before it in the Run."""


def _missing(transcript: Transcript, root: str) -> GroupError:
    """The GroupError of a Candidate that recorded `transcript`, then lacked command `root`."""
    missing = CommandMissing(root)
    error = GroupError(transcript, f"CommandMissing: {missing}")
    error.__cause__ = missing  # as `raise ... from` sets it in run_group
    return error


def _score(verdict: Verdict) -> tuple[float | None, int]:
    """The Score and failed lines of a Run of a passing Group, then `verdict`."""
    played = dataclasses.replace(SETS_BLOCKS, group_id=PASSING.id)
    passing = judge(PASSING, played, played)
    counted = totals(report_lines(_report(_result(passing), _result(verdict))))
    return counted.score, counted.failed


@pytest.mark.parametrize(
    "candidate",
    [
        _missing(Transcript(NEEDS_TICK.id, "pumpkin"), "tick"),
        _missing(EVERY_VALUE_WRONG, "kill"),
    ],
    ids=["setup", "teardown"],
)
def test_a_candidate_without_a_command_scores_no_higher_than_sending_every_value_wrong(
    candidate: GroupError,
) -> None:
    # Audit 2026-10-04 H1 (#284): `blocked` failed one line where every value wrong fails 4.
    wrong = judge(NEEDS_TICK, SETS_BLOCKS, EVERY_VALUE_WRONG)

    missing = judge(NEEDS_TICK, SETS_BLOCKS, candidate)

    (missing_score, missing_failed), (wrong_score, wrong_failed) = _score(missing), _score(wrong)
    assert missing_score is not None
    assert wrong_score is not None
    assert missing_score <= wrong_score
    assert missing_failed > wrong_failed, "every test case, and the Group's own line"


def test_a_command_missing_after_the_windows_keeps_the_comparisons_divergences() -> None:
    # Audit H1: blocks/* send `kill` only from the undo stack, after every window.
    wrong = judge(NEEDS_TICK, SETS_BLOCKS, EVERY_VALUE_WRONG)

    verdict = judge(NEEDS_TICK, SETS_BLOCKS, _missing(EVERY_VALUE_WRONG, "kill"))

    assert verdict.divergences == (_failed("requires /kill", bot=""), *wrong.divergences)
    assert verdict.detail == "the Candidate failed: requires /kill"


@pytest.mark.asyncio
async def test_a_command_missing_from_an_undo_callback_is_the_groups_cause() -> None:
    # blocks._frozen pushes `kill @e[type=minecraft:item]` on its undo stack.
    async def kill() -> None:
        root = "kill"
        raise CommandMissing(root)

    async def undoes(context: GroupContext) -> None:
        del context
        async with contextlib.AsyncExitStack() as undo:
            undo.push_async_callback(kill)

    candidate = await _play(Group(id="test/undoes", run=undoes), None)

    assert isinstance(candidate, GroupError)
    assert isinstance(candidate.__cause__, CommandMissing)


@pytest.mark.asyncio
async def test_a_command_missing_from_an_undo_callback_does_not_hide_the_groups_failure() -> None:
    # Review A #288: the Group failed first; the missing `kill` only came while undoing.
    async def kill() -> None:
        root = "kill"
        raise CommandMissing(root)

    async def fails_then_undoes(context: GroupContext) -> None:
        del context
        async with contextlib.AsyncExitStack() as undo:
            undo.push_async_callback(kill)
            msg = "the block never changed"
            raise TimeoutError(msg)

    group = Group(id="test/fails-then-undoes", run=fails_then_undoes)
    candidate = await _play(group, None)
    assert isinstance(candidate, GroupError)

    verdict = judge(group, Transcript(group.id, "vanilla"), candidate)

    first = "TimeoutError: the block never changed"
    assert verdict.divergences == (_failed(first, bot=""),)
    assert verdict.detail == f"the Candidate failed: {first}"


@pytest.mark.asyncio
async def test_a_command_the_reference_does_not_have_is_an_error() -> None:
    reference = await _play(NEEDS_TICK, None)
    assert isinstance(reference, GroupError)

    verdict = judge(NEEDS_TICK, reference, Transcript(NEEDS_TICK.id, "pumpkin"))

    detail = "the Reference failed: CommandMissing: the server has no /tick command"
    assert verdict == Verdict("test/needs-tick", Outcome.ERROR, detail=detail)


async def _reads_version(context: GroupContext) -> None:
    """A Group that trusts the status to name a version: an odd one makes it raise KeyError."""
    bot = await context.bot("status")
    reply = await bot.status()
    reply["version"]


READS_VERSION = Group(id="test/reads-version", run=_reads_version)
NO_VERSION = json.dumps({key: value for key, value in VANILLA_STATUS.items() if key != "version"})


@pytest.mark.asyncio
async def test_an_unexpected_exception_on_the_candidate_alone_is_a_mismatch() -> None:
    # #222: an exception type the Candidate is not expected to cause still scores against it.
    reference = await _play(READS_VERSION, status_server(_status_json(), []))
    candidate = await _play(READS_VERSION, status_server(NO_VERSION, []))
    assert isinstance(reference, Transcript)
    assert isinstance(candidate, GroupError)
    assert isinstance(candidate.__cause__, KeyError)

    verdict = judge(READS_VERSION, reference, candidate)

    assert verdict.outcome is Outcome.MISMATCH
    assert verdict.divergences[0] == _failed("KeyError: 'version'", bot="")  # the script raised
    assert verdict.detail == "the Candidate failed: KeyError: 'version'"


@pytest.mark.asyncio
async def test_an_unexpected_exception_on_the_reference_is_an_error() -> None:
    reference = await _play(READS_VERSION, status_server(NO_VERSION, []))
    candidate = await _play(READS_VERSION, status_server(_status_json(), []))
    assert isinstance(reference, GroupError)

    verdict = judge(READS_VERSION, reference, candidate)

    detail = "the Reference failed: KeyError: 'version'"
    assert verdict == Verdict("test/reads-version", Outcome.ERROR, detail=detail)


async def _mute(peer: Peer) -> None:
    """Take whatever each connection sends, answer nothing, until it closes."""
    with contextlib.suppress(EOFError):
        while True:
            await peer.recv()
