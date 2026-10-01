"""Commands for live tests, until Control (#17) sends them; and a Group that uses one.

An operator Bot sends an unsigned `chat_command` on its Connection. The Codec has no
schema for it yet, so `allow_commands` gives it one for a single test (monkeypatch
restores the table after): research and tests only, never in src/, where Control will
own commands.
"""

import dataclasses

import pytest

from mscts.bot import Bot
from mscts.codec import packets
from mscts.codec.packets import Direction, State
from mscts.codec.schema import Schema, String
from mscts.group import Group, GroupContext
from mscts.spec import ServerSpec
from mscts.target import TARGET

OPERATOR = "mscts_op"
"""The Bot the probe Group's ServerSpec makes an operator."""

CHAT_COMMAND = Schema(command=String(32767))
"""minecraft.wiki `Java_Edition_protocol/Packets` revision 3790659, "Chat Command": the
command, without its slash, as a String (32767)."""

BLOCK = "1 -60 1"
"""Where the probe sets a block: in the spawn chunk, just above the flat world's grass."""


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


async def _setblock_observed(context: GroupContext) -> None:
    """The operator sets a block inside a window; the watcher sees it change."""
    operator = await context.bot(OPERATOR)
    await operator.join()
    watcher = await context.bot("watcher")
    await watcher.join()
    await command(operator, "tick freeze")
    await operator.sync()
    async with context.observe("minecraft:block_update", "minecraft:system_chat"):
        await command(operator, f"setblock {BLOCK} minecraft:stone")
    await command(operator, f"setblock {BLOCK} minecraft:air")
    await operator.sync()


def _with_operator(spec: ServerSpec) -> ServerSpec:
    return dataclasses.replace(spec, operators=(OPERATOR,))


SETBLOCK_OBSERVED = Group(id="probe/setblock-observed", run=_setblock_observed, spec=_with_operator)
"""A probe Group, not registered: two Bots, an Observation window around one command."""
