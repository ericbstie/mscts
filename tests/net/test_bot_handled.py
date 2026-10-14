"""Bot.wait_until_handled: the proof that the server has handled what a Bot sent (#360)."""

import pytest

from mscts.bot import HANDLED_REQUESTS, Bot
from mscts.codec.packets import Codec, Direction, Packet
from mscts.net import ProtocolError
from mscts.target import TARGET
from mscts.transcript import Transcript
from tests.net.fakes import busy_server, status_server, with_bot

CODEC = Codec.for_target(TARGET)
REQUEST, ANSWER, PUNCH = "minecraft:client_command", "minecraft:award_stats", "minecraft:punch"
HANDLED = "minecraft:block_update"
"""What `busy_server` sends once it has handled the Bot's action, before it answers."""


def barrier_after(transcript: Transcript, t_ns: int) -> list[tuple[Direction, str]]:
    """Each request, answer and `HANDLED` from `t_ns` on, in time order."""
    return [
        (event.packet.direction, event.packet.name)
        for event in transcript.events
        if event.t_ns > t_ns and event.packet.name in {REQUEST, ANSWER, HANDLED}
    ]


@pytest.mark.parametrize("stray", [False, True], ids=["answers-only", "a-stray-first"])
def test_wait_until_handled_returns_only_once_the_server_handled_the_action(*, stray: bool) -> None:
    # #360: the stray is an award_stats a Candidate sends unasked as the first request
    # arrives (#169). Taken as an answer, it would end a one-request proof early.
    transcript = Transcript(group_id="test/handled", server="fake")
    seen: list[Packet] = []

    async def use(bot: Bot) -> tuple[list[str], int]:
        await bot.join()
        joined_at = transcript.now_ns()
        await bot.swing()
        await bot.wait_until_handled()
        return [event.packet.name for event in transcript.events], joined_at

    (names, joined_at), _ = with_bot(CODEC, transcript, busy_server(seen, stray=stray), use)

    assert HANDLED in names, "it returned before the server had handled the action"
    barrier = barrier_after(transcript, joined_at)
    sent = [(Direction.SERVERBOUND, REQUEST)] * HANDLED_REQUESTS
    assert barrier[:HANDLED_REQUESTS] == sent, "every request goes out before any answer"
    served = [packet.name for packet in seen if packet.name in {PUNCH, REQUEST}]
    assert served == [PUNCH, *[REQUEST] * HANDLED_REQUESTS], "the requests follow the action"


def test_wait_until_handled_refuses_a_bot_that_is_not_in_play() -> None:
    transcript = Transcript(group_id="test/handled", server="fake")

    async def use(bot: Bot) -> None:
        with pytest.raises(ProtocolError, match="needs a Bot in play, not one in handshake"):
            await bot.wait_until_handled()

    with_bot(CODEC, transcript, status_server("{}", []), use)
    assert transcript.events == []
