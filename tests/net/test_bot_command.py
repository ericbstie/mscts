"""Bot.command: a command from the Bot's player."""

import pytest

from mscts.bot import Bot
from mscts.codec.packets import Codec, Packet
from mscts.net import ProtocolError
from mscts.target import TARGET
from mscts.transcript import Transcript
from tests.net.fakes import play_server, status_server, with_bot

CODEC = Codec.for_target(TARGET)


def test_command_sends_the_text_as_a_chat_command() -> None:
    transcript = Transcript(group_id="test/command", server="fake")
    seen: list[Packet] = []

    async def use(bot: Bot) -> None:
        await bot.join()
        await bot.command("setblock 1 -60 1 minecraft:stone")
        await bot.sync()  # the server has read the command by its first answer

    with_bot(CODEC, transcript, play_server(seen), use)

    commands = [p.fields for p in seen if p.name == "minecraft:chat_command"]
    assert commands == [{"command": "setblock 1 -60 1 minecraft:stone"}]


def test_command_refuses_a_bot_that_is_not_in_play() -> None:
    transcript = Transcript(group_id="test/command", server="fake")

    async def use(bot: Bot) -> None:
        with pytest.raises(
            ProtocolError, match="command needs a Bot in play, not one in handshake"
        ):
            await bot.command("tick freeze")

    with_bot(CODEC, transcript, status_server("{}", []), use)
    assert transcript.events == []
