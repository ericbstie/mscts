"""Control's Bot sets the world up: what it receives is recorded, and never compared."""

from mscts.codec.packets import State
from mscts.compare import Outcome, compare
from mscts.spec import CONTROL_PLAYER
from tests.compare.build import packet, transcript


def test_control_is_the_bot_called_control() -> None:
    assert CONTROL_PLAYER == "control"


def test_what_control_receives_is_never_compared() -> None:
    reference = transcript(
        ("alice", packet("minecraft:login_finished", b"\x01", state=State.LOGIN)),
        (CONTROL_PLAYER, packet("minecraft:system_chat", b"\x01")),
        (CONTROL_PLAYER, packet("minecraft:block_update", b"\x01")),
    )
    candidate = transcript(
        ("alice", packet("minecraft:login_finished", b"\x01", state=State.LOGIN)),
        (CONTROL_PLAYER, packet("minecraft:system_chat", b"\x02")),
        server="pumpkin",
    )

    verdict = compare(reference, candidate, ())

    assert (verdict.outcome, verdict.divergences) == (Outcome.MATCH, ())
    assert len(reference.events) == 3  # still recorded


def test_a_control_on_one_side_only_is_no_divergence() -> None:
    reference = transcript(("alice", packet("minecraft:block_update", b"\x01")))
    candidate = transcript(
        ("alice", packet("minecraft:block_update", b"\x01")),
        (CONTROL_PLAYER, packet("minecraft:system_chat", b"\x02")),
        server="pumpkin",
    )

    assert compare(reference, candidate, ()).outcome is Outcome.MATCH


def test_every_other_bot_is_still_compared() -> None:
    reference = transcript(("controller", packet("minecraft:block_update", b"\x01")))
    candidate = transcript(("controller", packet("minecraft:block_update", b"\x02")))

    assert compare(reference, candidate, ()).outcome is Outcome.MISMATCH
