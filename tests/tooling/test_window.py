from support.window import window_since

from mscts.codec.packets import Direction, Packet, State
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN
from mscts.transcript import Mark, Transcript

PACKET = Packet(
    state=State.PLAY,
    direction=Direction.CLIENTBOUND,
    name="minecraft:block_update",
    packet_id=0x08,
    payload=b"",
    fields=None,
)


def _transcript(*marks: Mark) -> Transcript:
    """A Transcript whose clock started long ago, so any small `t_ns` can be recorded."""
    return Transcript(group_id="blocks", server="vanilla", marks=list(marks), start_ns=0)


def test_a_late_recorded_packet_is_read_by_its_time_not_by_where_it_landed() -> None:
    transcript = _transcript(Mark(t_ns=20, label=OBSERVE_OPEN))
    transcript.record("watcher", PACKET, t_ns=10)
    first = len(transcript.events)
    inside = transcript.record("watcher", PACKET, t_ns=30)
    transcript.marks.append(Mark(t_ns=40, label=f"{OBSERVE_CLOSE} watcher"))
    transcript.record("watcher", PACKET, t_ns=50)
    late_inside = transcript.record("watcher", PACKET, t_ns=25)
    transcript.record("watcher", PACKET, t_ns=15)  # recorded late, stamped before the window

    assert transcript.events[first].t_ns == 15  # an index window would take it
    assert window_since(transcript, "watcher", 0) == [late_inside, inside]


def test_a_window_with_no_close_mark_runs_to_the_end() -> None:
    transcript = _transcript(Mark(t_ns=20, label=OBSERVE_OPEN))
    later = transcript.record("watcher", PACKET, t_ns=90)
    assert window_since(transcript, "watcher", 0) == [later]


def test_a_window_with_no_close_mark_ends_where_the_next_one_opens() -> None:
    transcript = _transcript(
        Mark(t_ns=20, label=OBSERVE_OPEN),
        Mark(t_ns=60, label=OBSERVE_OPEN),
        Mark(t_ns=80, label=f"{OBSERVE_CLOSE} watcher"),
    )
    inside = transcript.record("watcher", PACKET, t_ns=30)
    transcript.record("watcher", PACKET, t_ns=70)
    assert window_since(transcript, "watcher", 0) == [inside]


def test_the_bots_own_close_mark_ends_its_window_before_the_unnamed_one() -> None:
    transcript = _transcript(
        Mark(t_ns=20, label=OBSERVE_OPEN),
        Mark(t_ns=40, label=f"{OBSERVE_CLOSE} watcher"),
        Mark(t_ns=60, label=OBSERVE_CLOSE),
    )
    inside = transcript.record("watcher", PACKET, t_ns=30)
    transcript.record("watcher", PACKET, t_ns=50)
    other = transcript.record("control", PACKET, t_ns=50)
    assert window_since(transcript, "watcher", 0) == [inside]
    assert window_since(transcript, "control", 0) == [other]


def test_the_window_read_is_the_first_to_open_since_the_time_given() -> None:
    transcript = _transcript(
        Mark(t_ns=20, label=OBSERVE_OPEN),
        Mark(t_ns=40, label=OBSERVE_CLOSE),
        Mark(t_ns=60, label=f"{OBSERVE_OPEN} minecraft:block_update"),
    )
    transcript.record("watcher", PACKET, t_ns=30)
    second = transcript.record("watcher", PACKET, t_ns=70)
    assert window_since(transcript, "watcher", 21) == [second]


def test_nothing_is_in_a_window_when_none_opened_since_the_time_given() -> None:
    transcript = _transcript(Mark(t_ns=20, label=OBSERVE_OPEN))
    transcript.record("watcher", PACKET, t_ns=30)
    assert window_since(transcript, "watcher", 21) == []
