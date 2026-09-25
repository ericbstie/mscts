import dataclasses
import time

import pytest

from mscts.codec.packets import Direction, Packet, State
from mscts.transcript import Event, Mark, Transcript

PACKET = Packet(
    state=State.STATUS,
    direction=Direction.CLIENTBOUND,
    name="minecraft:pong_response",
    packet_id=0x01,
    payload=bytes(8),
    fields={"timestamp": 0},
)


def test_event_holds_time_bot_and_packet() -> None:
    event = Event(t_ns=5, bot="alice", packet=PACKET)
    assert (event.t_ns, event.bot, event.packet) == (5, "alice", PACKET)


def test_mark_holds_time_and_label() -> None:
    mark = Mark(t_ns=7, label="status:start")
    assert (mark.t_ns, mark.label) == (7, "status:start")


@pytest.mark.parametrize(
    ("value", "field"),
    [
        (Event(t_ns=5, bot="alice", packet=PACKET), "t_ns"),
        (Event(t_ns=5, bot="alice", packet=PACKET), "bot"),
        (Event(t_ns=5, bot="alice", packet=PACKET), "packet"),
        (Mark(t_ns=7, label="status:start"), "t_ns"),
        (Mark(t_ns=7, label="status:start"), "label"),
    ],
)
def test_event_and_mark_are_frozen(value: object, field: str) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(value, field, getattr(value, field))


def test_event_and_mark_have_slots() -> None:
    assert not hasattr(Event(t_ns=5, bot="alice", packet=PACKET), "__dict__")
    assert not hasattr(Mark(t_ns=7, label="status:start"), "__dict__")


def test_transcript_starts_empty() -> None:
    transcript = Transcript(scenario_id="status/basic", server="vanilla")
    assert (transcript.scenario_id, transcript.server) == ("status/basic", "vanilla")
    assert transcript.events == []
    assert transcript.marks == []


def test_transcript_starts_on_the_monotonic_clock() -> None:
    before = time.monotonic_ns()
    transcript = Transcript(scenario_id="status/basic", server="vanilla")
    after = time.monotonic_ns()
    assert before <= transcript.start_ns <= after


def test_now_ns_counts_monotonic_nanoseconds_since_the_start() -> None:
    transcript = Transcript(
        scenario_id="status/basic", server="vanilla", start_ns=time.monotonic_ns() - 5_000_000
    )
    before = time.monotonic_ns() - transcript.start_ns
    now = transcript.now_ns()
    after = time.monotonic_ns() - transcript.start_ns
    assert 5_000_000 <= before <= now <= after


def test_transcripts_with_equal_contents_are_equal_whatever_their_start() -> None:
    first = Transcript(scenario_id="status/basic", server="vanilla", start_ns=1)
    second = Transcript(scenario_id="status/basic", server="vanilla", start_ns=2)
    assert first == second
