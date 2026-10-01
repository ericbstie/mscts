"""Play-state schemas for commands: the command a player sends, and what the server answers.

Field layouts: minecraft.wiki `Java_Edition_protocol/Packets`, revision 3790659
(2026-09-23, "26.3, protocol 777"), raw wikitext, "Chat Command" and "System Chat Message".
Checked against the 26.3 jar with `javap` (docs/research/2026-10-01-control.md):
`ServerboundChatCommandPacket` reads its command with `FriendlyByteBuf.readUtf()`, at most
32767; `ClientboundSystemChatPacket.STREAM_CODEC` is a text component
(`ComponentSerialization.TRUSTED_STREAM_CODEC`, network NBT) then a Boolean.
"""

from collections.abc import Mapping

from mscts.codec.schema import BOOL, NBT, Schema, String

SERVERBOUND: Mapping[str, Schema] = {
    # Chat Command: a command, without its slash, run as the player (unsigned: a command
    # with no signed argument).
    "minecraft:chat_command": Schema(command=String(32767)),
}

CLIENTBOUND: Mapping[str, Schema] = {
    # System Chat Message: a message from the server, such as a command's feedback. The
    # content is a text component, kept as its NBT bytes until text components decode.
    "minecraft:system_chat": Schema(content=NBT, overlay=BOOL),
}
