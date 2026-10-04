"""Bot.chat and Bot.signed_command: what the Bot's player says, as a client with no chat session."""

from collections.abc import Awaitable, Callable

import pytest

from mscts.bot import Bot
from mscts.codec.packets import Codec, Packet
from mscts.net import ProtocolError
from mscts.target import TARGET
from mscts.transcript import Transcript
from tests.net.fakes import play_server, status_server, with_bot

CODEC = Codec.for_target(TARGET)

UNSIGNED = {"message_count": 0, "acknowledged": bytes(3), "checksum": 1}
"""What a vanilla client with no chat session fills in besides the text and its time: nothing
acknowledged, and the checksum of an empty last-seen set, 1 (LastSeenMessages.computeChecksum)."""


def sent(use: Callable[[Bot], Awaitable[None]]) -> list[Packet]:
    """What `use` makes a Bot send to a fake server that joins it like vanilla."""
    transcript = Transcript(group_id="test/chat", server="fake")
    seen: list[Packet] = []
    with_bot(CODEC, transcript, play_server(seen), use)
    return seen


def fields_of(packets: list[Packet], name: str) -> list[dict[str, object]]:
    return [dict(p.fields or {}) for p in packets if p.name == name]


def test_chat_sends_the_message_with_a_fixed_time_and_salt_and_no_signature() -> None:
    async def use(bot: Bot) -> None:
        await bot.join()
        await bot.chat("hello")
        await bot.chat("again")
        await bot.sync()  # the server has read both by its first answer

    chats = fields_of(sent(use), "minecraft:chat")

    assert [chat.pop("message") for chat in chats] == ["hello", "again"]
    assert chats[0] == chats[1]
    assert {key: chats[0][key] for key in ("signature", *UNSIGNED)} == {
        "signature": None
    } | UNSIGNED


def test_signed_command_sends_the_command_with_no_argument_signature() -> None:
    async def use(bot: Bot) -> None:
        await bot.join()
        await bot.signed_command("say hi")
        await bot.sync()

    commands = fields_of(sent(use), "minecraft:chat_command_signed")

    assert [(c["command"], c["argument_signatures"]) for c in commands] == [("say hi", [])]
    assert {key: commands[0][key] for key in UNSIGNED} == UNSIGNED


def test_chat_and_signed_command_send_the_same_time_and_salt() -> None:
    async def use(bot: Bot) -> None:
        await bot.join()
        await bot.chat("hello")
        await bot.signed_command("say hi")
        await bot.sync()

    packets = sent(use)
    (chat,) = fields_of(packets, "minecraft:chat")
    (command,) = fields_of(packets, "minecraft:chat_command_signed")

    assert (chat["timestamp"], chat["salt"]) == (command["timestamp"], command["salt"])


@pytest.mark.parametrize("operation", ["chat", "signed_command"])
def test_chat_and_signed_command_refuse_a_bot_that_is_not_in_play(operation: str) -> None:
    transcript = Transcript(group_id="test/chat", server="fake")

    async def use(bot: Bot) -> None:
        with pytest.raises(
            ProtocolError, match=f"{operation} needs a Bot in play, not one in handshake"
        ):
            await getattr(bot, operation)("hello")

    with_bot(CODEC, transcript, status_server("{}", []), use)
    assert transcript.events == []
