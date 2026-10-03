"""Timelines: a play's Transcript as text, to diagnose a flaky Self-check (#162)."""

from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN
from mscts.timeline import timeline
from tests.compare.build import SERVERBOUND, packet, transcript


def test_a_timeline_lists_each_packet_and_mark_in_time_order_and_whether_a_window_takes_it() -> (
    None
):
    played = transcript(
        ("alice", packet("minecraft:system_chat")),
        OBSERVE_OPEN,
        ("alice", packet("minecraft:client_command", direction=SERVERBOUND)),
        ("alice", packet("minecraft:block_update")),
        OBSERVE_CLOSE,
        group_id="probe/block",
        server="vanilla",
    )

    assert timeline(played).splitlines() == [
        "probe/block on vanilla",
        "       0.000 ms  alice  received minecraft:system_chat, outside the window",
        "       1.000 ms         mark observe:open",
        "       2.000 ms  alice  sent minecraft:client_command",
        "       3.000 ms  alice  received minecraft:block_update, inside the window",
        "       4.000 ms         mark observe:close",
    ]


def test_each_award_stats_says_how_long_after_its_bots_last_one_it_arrived() -> None:
    answer = packet("minecraft:award_stats")
    played = transcript(("alice", answer), ("bob", answer), ("bob", answer), ("alice", answer))

    answers = [line for line in timeline(played).splitlines() if "award_stats" in line]

    assert [line.split("award_stats")[1] for line in answers] == [
        "",
        "",
        ", 1.000 ms after bob's last",
        ", 3.000 ms after alice's last",
    ]
