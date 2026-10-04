"""Chat Groups: what players see of each other's chat, of chat commands, and of joins and leaves.

A Bot called `listener` is in the world for every case, and what it is sent is compared with
what the Bot that speaks is sent. Each case has a window of its own, and the window waits, in
its body, for the message to reach the listener: the listener sent nothing, so its barrier
alone does not cover what another Bot's action sends it.

A Bot speaks the way the vanilla client does with no chat signing keys, as every offline
player: `Bot.chat` for a message, `Bot.signed_command` for a command with a message argument.
Vanilla answers both with `player_chat` (an unsigned chat_command would get
`disguised_chat` instead: docs/research/2026-10-04-chat.md).
"""

import contextlib
from collections.abc import Callable
from dataclasses import dataclass, replace

from mscts.bot import Bot
from mscts.group import GroupContext, group
from mscts.spec import ServerSpec

LISTENER = "listener"
"""The Bot that is in the world for every case, and is sent what the others say."""

SPEAKER = "speaker"
"""The Bot that says something, in `chat/player` and, as an operator, in `chat/commands`."""

FEEDBACK_TIMEOUT_S = 10.0
"""How long a Bot waits for a message, or its kick, to arrive: a Bot's bound."""

PACKETS = (
    "minecraft:player_chat",
    "minecraft:system_chat",
    "minecraft:disguised_chat",
    "minecraft:disconnect",
    "minecraft:player_info_update",
    "minecraft:player_info_remove",
)
"""The packets a window compares: the chat messages, a kick's reason and the player list."""

_PLAYER_CHAT = "minecraft:player_chat"
_SYSTEM_CHAT = "minecraft:system_chat"
_SAID = (_PLAYER_CHAT, "minecraft:disguised_chat")
"""What a window waits for when a player says something: vanilla sends `player_chat`. A
server that sends `disguised_chat` instead ends the window too, so the Report shows the
difference and the Group goes on (#270)."""

_COMMAND_SAID = (*_SAID, _SYSTEM_CHAT)
"""What a window waits for when a player runs a message command: what a player says, or a
system message, as Pumpkin sends `/teammsg`. The listener hears nothing else meanwhile."""
_DISCONNECT = "minecraft:disconnect"


def _with_operator(name: str) -> Callable[[ServerSpec], ServerSpec]:
    """A ServerSpec change that makes `name` an operator, besides whoever the spec names."""

    def change(spec: ServerSpec) -> ServerSpec:
        return replace(spec, operators=(*spec.operators, name))

    return change


async def _joined(context: GroupContext, name: str) -> Bot:
    """A Bot called `name` that has joined the world."""
    bot = await context.bot(name)
    await bot.join()
    return bot


# `chat/player`

_PLAYER_MESSAGES = (
    "Hello, world!",
    "The rules are at https://www.minecraft.net/en-us/eula",
)
"""What the speaker says, each in a window of its own: a plain message, and one with a link."""


@group("chat/player")
async def player(context: GroupContext) -> None:
    """The speaker says a plain message, then one with a link, and the listener is sent each."""
    listener = await _joined(context, LISTENER)
    speaker = await _joined(context, SPEAKER)
    for message in _PLAYER_MESSAGES:
        async with context.observe(*PACKETS):
            await speaker.chat(message)
            await listener.expect(*_SAID, timeout_s=FEEDBACK_TIMEOUT_S)


# `chat/commands`

_TEAM = "mscts"
"""The team the speaker and the listener are on, for `/teammsg`."""


@dataclass(frozen=True, slots=True)
class _Command:
    """A command the speaker runs, and the packet that brings it to the listener.

    Attributes:
        text: The command, without its `/`.
        signed: Whether the vanilla client sends it signed: it has a message argument.
        arrives_as: The packets that bring it to the listener, of which the window waits for
            the first.
    """

    text: str
    signed: bool
    arrives_as: tuple[str, ...]


_COMMANDS = (
    _Command("me waves to everyone", signed=True, arrives_as=_COMMAND_SAID),
    _Command("say Hello from the speaker", signed=True, arrives_as=_COMMAND_SAID),
    _Command(f"msg {LISTENER} This is a whisper", signed=True, arrives_as=_COMMAND_SAID),
    _Command(
        'tellraw @a {"text":"Formatted text","color":"gold","bold":true}',
        signed=False,
        arrives_as=(_SYSTEM_CHAT,),
    ),
    _Command("teammsg Hello, team", signed=True, arrives_as=_COMMAND_SAID),
)
"""What the speaker runs, each in a window of its own."""


@group("chat/commands", spec=_with_operator(SPEAKER))
async def commands(context: GroupContext) -> None:
    """The speaker, an operator, runs each chat command, and the listener is sent what it says."""
    listener = await _joined(context, LISTENER)
    speaker = await _joined(context, SPEAKER)
    async with contextlib.AsyncExitStack() as undo:
        await context.control.run(f"team add {_TEAM}")
        undo.push_async_callback(context.control.run, f"team remove {_TEAM}")
        for name in (SPEAKER, LISTENER):
            await context.control.run(f"team join {_TEAM} {name}")
        for command in _COMMANDS:
            # The window's opening barrier takes what Control's commands told the speaker.
            async with context.observe(*PACKETS):
                if command.signed:
                    await speaker.signed_command(command.text)
                else:
                    await speaker.command(command.text)
                await listener.expect(*command.arrives_as, timeout_s=FEEDBACK_TIMEOUT_S)


# `chat/join-leave`

JOINER = "joiner"
"""The Bot that joins and leaves while the listener is in the world."""


@group("chat/join-leave")
async def join_leave(context: GroupContext) -> None:
    """The joiner joins, then leaves, while the listener is in the world."""
    listener = await _joined(context, LISTENER)
    joiner = await context.bot(JOINER)
    async with context.observe(*PACKETS):
        await joiner.join()
        await listener.expect(_SYSTEM_CHAT, timeout_s=FEEDBACK_TIMEOUT_S)
    async with context.observe(*PACKETS):
        await joiner.close()
        await listener.expect(_SYSTEM_CHAT, timeout_s=FEEDBACK_TIMEOUT_S)


# `chat/limits`

TALKER, OPERATOR = "talker", "operator"
"""A Bot that says the longest message vanilla takes, and an operator that sends too many."""

LONG, SECTION, SPAMMER = "long", "section", "spammer"
"""The Bots vanilla kicks: for a message that is too long, for a `§` and for too many."""

SPAM_MESSAGES = 15
"""How many messages a Bot sends at once, in one write, to be kicked for spam.

Each message adds 20 to the player's count, and each tick takes 1 away; vanilla kicks a
player who is not an operator once the count reaches 200 (`chat-spam-threshold-seconds` 10,
26.3 javap). Ten messages within one tick are the kick, but a tick that falls inside the
burst leaves the count at 199. Fifteen kick however the ticks fall, unless 100 ticks pass
during the burst. `/tick freeze` would not help: the count goes down with every tick of the
server, frozen or not. An operator is never kicked, so it sends the same.
"""

CHATTER = "chatter"
"""A Bot that is not an operator and sends `UNDER_SPAM_MESSAGES` messages at once."""

UNDER_SPAM_MESSAGES = 9
"""How many messages the chatter sends at once, in one write, and is not kicked for.

Nine messages add 180 to the player's count, under the 200 that vanilla kicks at, however the
ticks fall. With the spammer's `SPAM_MESSAGES`, this pins the kick to the 10th to 15th message.
"""

_KICK_PACKETS = (_DISCONNECT, _SYSTEM_CHAT, "minecraft:player_info_remove")
"""What the spam kick's window compares: the kick, the listener being told the Bot left, and
the player list. How many messages got through before the kick depends on where the ticks
fell, so the chat itself is not compared there."""


@group("chat/limits", spec=_with_operator(OPERATOR))
async def limits(context: GroupContext) -> None:
    """Messages of 256 and 257 characters, a `§`, and many at once, by players and an operator."""
    listener = await _joined(context, LISTENER)
    talker = await _joined(context, TALKER)
    async with context.observe(*PACKETS):
        await talker.chat("x" * 256)
        await listener.expect(*_SAID, timeout_s=FEEDBACK_TIMEOUT_S)
    operator = await _joined(context, OPERATOR)
    async with context.observe(*PACKETS):
        await operator.chat_at_once(*_numbered(SPAM_MESSAGES))
        for _ in range(SPAM_MESSAGES):
            await listener.expect(*_SAID, timeout_s=FEEDBACK_TIMEOUT_S)
    chatter = await _joined(context, CHATTER)
    async with context.observe(*PACKETS):
        await chatter.chat_at_once(*_numbered(UNDER_SPAM_MESSAGES))
        for _ in range(UNDER_SPAM_MESSAGES):
            await listener.expect(*_SAID, timeout_s=FEEDBACK_TIMEOUT_S)
    for name, messages, packets in (
        (LONG, ("x" * 257,), PACKETS),
        (SECTION, ("§cRed text",), PACKETS),
        (SPAMMER, _numbered(SPAM_MESSAGES), _KICK_PACKETS),
    ):
        await _kicked(context, listener, name, messages, packets)


def _numbered(count: int) -> tuple[str, ...]:
    """The messages a Bot sends at once: `Message 1` to `Message <count>`."""
    return tuple(f"Message {number + 1}" for number in range(count))


async def _kicked(
    context: GroupContext,
    listener: Bot,
    name: str,
    messages: tuple[str, ...],
    packets: tuple[str, ...],
) -> None:
    """Join a Bot called `name`, and in a window comparing `packets`, send `messages` at once.

    The window waits for the Bot's kick, then for the listener to be told the Bot left.
    """
    bot = await _joined(context, name)
    async with context.observe(*packets):
        await bot.chat_at_once(*messages)
        await bot.expect(_DISCONNECT, timeout_s=FEEDBACK_TIMEOUT_S)
        await listener.expect(_SYSTEM_CHAT, timeout_s=FEEDBACK_TIMEOUT_S)
