"""What a Bot operation's TimeoutError says (#427): which Bot waited, for what, and how long."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import pytest
from support.hang import hang

from mscts.bot import Bot
from mscts.codec.packets import Codec
from mscts.net import Connection
from mscts.transcript import Transcript
from tests.net.fakes import Peer, join_server, with_bot

LIMIT_S = 0.05
JOINED_LIMIT_S = 0.2
"""Longer, for the cases that join first: the join must finish within it."""


@dataclass(frozen=True)
class Case:
    operation: Callable[[Bot], Awaitable[object]]
    waited_for: str


async def silent(peer: Peer) -> None:
    await peer.recv()
    await peer.recv()
    await peer.eof()


async def _ping(bot: Bot) -> None:
    await bot.ping(1)


ANSWERS = {
    "status": Case(Bot.status, "minecraft:status_response"),
    "ping": Case(_ping, "minecraft:pong_response"),
    "join": Case(Bot.join, "the first minecraft:chunk_batch_finished"),
}


@pytest.mark.parametrize("case", ANSWERS.values(), ids=ANSWERS.keys())
def test_an_operation_waiting_for_an_answer_says_which_packet_it_waited_for(
    codec: Codec, transcript: Transcript, case: Case
) -> None:
    async def raises(bot: Bot) -> str:
        with pytest.raises(TimeoutError) as caught:
            await case.operation(bot)
        return str(caught.value)

    text, _ = with_bot(codec, transcript, silent, raises, timeout_s=LIMIT_S)

    assert text == f"alice waited {LIMIT_S} s for {case.waited_for}"


async def _signed_command(bot: Bot) -> None:
    await bot.signed_command("say hi")


async def _command(bot: Bot) -> None:
    await bot.command("say hi")


async def _chat(bot: Bot) -> None:
    await bot.chat("hi")


async def _chat_at_once(bot: Bot) -> None:
    await bot.chat_at_once("hi", "again")


async def _tick(bot: Bot) -> None:
    await bot.tick()


async def _click(bot: Bot) -> None:
    await bot.click(9)  # a slot of the inventory's 27


async def _place_recipe(bot: Bot) -> None:
    await bot.place_recipe(1)


TAKEN = "the server to take"
STATISTICS = "the minecraft:award_stats answers to its statistics requests"

IN_PLAY = {
    "command": Case(_command, f"{TAKEN} minecraft:chat_command"),
    "signed_command": Case(_signed_command, f"{TAKEN} minecraft:chat_command_signed"),
    "chat": Case(_chat, f"{TAKEN} minecraft:chat"),
    "chat_at_once": Case(_chat_at_once, f"{TAKEN} minecraft:chat"),
    "tick": Case(_tick, f"{TAKEN} a client tick"),
    "close_container": Case(Bot.close_container, f"{TAKEN} minecraft:container_close"),
    "click": Case(_click, f"{TAKEN} minecraft:container_click"),
    "place_recipe": Case(_place_recipe, f"{TAKEN} minecraft:place_recipe"),
    "respawn": Case(Bot.respawn, "minecraft:respawn, then minecraft:chunk_batch_finished"),
    "sync": Case(Bot.sync, STATISTICS),
    "wait_until_handled": Case(Bot.wait_until_handled, STATISTICS),
}


@pytest.mark.parametrize("case", IN_PLAY.values(), ids=IN_PLAY.keys())
def test_an_operation_that_cannot_send_says_what_the_server_was_to_take(
    codec: Codec, transcript: Transcript, monkeypatch: pytest.MonkeyPatch, case: Case
) -> None:
    async def raises(bot: Bot) -> str:
        await bot.join()
        # A server that stops reading eventually blocks the client's writes.
        monkeypatch.setattr(Connection, "send", hang)
        monkeypatch.setattr(Connection, "send_all", hang)
        with pytest.raises(TimeoutError) as caught:
            await case.operation(bot)
        return str(caught.value)

    text, _ = with_bot(codec, transcript, join_server([]), raises, timeout_s=JOINED_LIMIT_S)

    assert text == f"alice waited {JOINED_LIMIT_S} s for {case.waited_for}"
