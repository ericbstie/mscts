"""Commands a live test's own operator Bot sends: the item stack tests use them.

An operator Bot sends an unsigned `chat_command` on its Connection. These helpers came
before `Bot.command` and Control (#17), which a Group uses to run commands; the probe
Group they also served is in `support.probe` and runs its commands through Control.
"""

import pytest

from mscts.bot import Bot
from mscts.codec import packets
from mscts.codec.packets import Direction, State
from mscts.codec.schema import Schema, String
from mscts.target import TARGET

OPERATOR = "mscts_op"
"""The Bot a test's ServerSpec makes an operator."""

CHAT_COMMAND = Schema(command=String(32767))
"""minecraft.wiki `Java_Edition_protocol/Packets` revision 3790659, "Chat Command": the
command, without its slash, as a String (32767)."""


def allow_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give the serverbound play `chat_command` a schema in every Codec loaded from now on."""
    version = TARGET.minecraft_version
    schemas = dict(packets._SCHEMAS[version])  # noqa: SLF001 - test only, restored after
    key = (State.PLAY, Direction.SERVERBOUND)
    schemas[key] = {**schemas[key], "minecraft:chat_command": CHAT_COMMAND}
    monkeypatch.setattr(packets, "_SCHEMAS", {**packets._SCHEMAS, version: schemas})  # noqa: SLF001


async def command(bot: Bot, text: str) -> None:
    """Send `text`, without its slash, as a command from `bot` (`allow_commands` first)."""
    await bot._connection.send("minecraft:chat_command", command=text)  # noqa: SLF001
