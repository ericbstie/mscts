"""Play-state schemas for chat: what a player says, and the chat messages the server sends.

`system_chat` and `chat_command` are in `commands.py`, with the rest of a command's travel.

Field layouts: minecraft.wiki `Java_Edition_protocol/Packets`, revision 3790659 (2026-09-23,
"26.3, protocol 777"), raw wikitext, "Chat Message", "Signed Chat Command", "Player Chat
Message" and "Disguised Chat Message". Checked against the 26.3 jar with `javap`:
`ServerboundChatPacket.STREAM_CODEC` is `stringUtf8(256)`, `INSTANT` (a Long of epoch
milliseconds), a Long salt, an optional `MessageSignature` (256 bytes, no length) and
`LastSeenMessages$Update` (a VarInt, a `fixedBitSet(20)` of 3 bytes and a Byte checksum).
`ServerboundChatCommandSignedPacket` is a String, `INSTANT`, a Long, `ArgumentSignatures` (at
most 8 entries) and `LastSeenMessages$Update`. `ClientboundPlayerChatPacket` is a VarInt, a
UUID and a VarInt, the optional signature, `SignedMessageBody$Packed` (`stringUtf8(256)`,
`INSTANT`, a Long, and at most 20 `MessageSignature$Packed`: a VarInt id + 1, or 0 and the
whole signature), an optional text component, `FilterMask` and `ChatType$Bound` (a
`ChatType` holder, the sender's name and an optional target name).
`ClientboundDisguisedChatPacket` is a text component and a `ChatType$Bound`.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from mscts.codec.schema import (
    BYTE,
    LONG,
    UUID,
    VAR_INT,
    PrefixedArray,
    PrefixedOptional,
    Schema,
    String,
    Tagged,
)
from mscts.codec.shapes import ENUM, NBT_TAG, TEXT_COMPONENT, Holder
from mscts.codec.wire import Reader, WireError, Writer

_MESSAGE_MAX = 256
"""The most characters vanilla reads in a chat message (`stringUtf8(256)`) and sends in one."""


@dataclass(frozen=True, slots=True)
class _FixedBytes:
    """Exactly `size` bytes and no length: a signature, or a fixed bit set's bytes."""

    size: int

    def read(self, reader: Reader) -> bytes:
        return reader.raw(self.size)

    def write(self, writer: Writer, value: object) -> None:
        if not isinstance(value, bytes) or len(value) != self.size:
            got = f"{len(value)} byte(s)" if isinstance(value, bytes) else type(value).__name__
            msg = f"expected exactly {self.size} bytes, got {got}"
            raise WireError(msg)
        writer.raw(value)


_SIGNATURE = _FixedBytes(256)
"""A `MessageSignature`: 256 bytes."""

_DECORATION = Schema(
    translation_key=String(32767),
    parameters=PrefixedArray(ENUM),  # sender 0, target 1, content 2
    style=NBT_TAG,
)
"""How a chat type shows a message (`ChatTypeDecoration.STREAM_CODEC`)."""

_CHAT_TYPE = Holder(Schema(chat=_DECORATION, narration=_DECORATION))
"""A `minecraft:chat_type` registry id (from `registry_data`), or a chat type in place."""

_CHAT_TYPE_BOUND = {
    "chat_type": _CHAT_TYPE,
    "sender_name": TEXT_COMPONENT,
    "target_name": PrefixedOptional(TEXT_COMPONENT),
}
"""`ChatType$Bound`: the chat type, and the names it fills in."""

SERVERBOUND: Mapping[str, Schema] = {
    # Chat Message: what a player says. A vanilla client with no chat session (every Bot: offline
    # players have no keys) sends no signature. `message_count`, `acknowledged` and `checksum`
    # say which signed messages it has seen. Vanilla reads at most _MESSAGE_MAX characters and
    # kicks a player who sends more; the schema writes more, so a Group can test that.
    "minecraft:chat": Schema(
        message=String(32767),
        timestamp=LONG,
        salt=LONG,
        signature=PrefixedOptional(_SIGNATURE),
        message_count=VAR_INT,
        acknowledged=_FixedBytes(3),
        checksum=BYTE,
    ),
    # Signed Chat Command: a command with a message argument (`/say`, `/msg`), which the vanilla
    # client sends this way, signing each such argument. A client with no chat session signs
    # none, and the server takes each message as unsigned.
    "minecraft:chat_command_signed": Schema(
        command=String(32767),
        timestamp=LONG,
        salt=LONG,
        argument_signatures=PrefixedArray(
            Schema(argument_name=String(16), signature=_SIGNATURE), max_length=8
        ),
        message_count=VAR_INT,
        acknowledged=_FixedBytes(3),
        checksum=BYTE,
    ),
}

CLIENTBOUND: Mapping[str, Schema] = {
    # Player Chat Message: a message a player said. `global_index` counts the messages this
    # client was sent, `index` the sender's. A previous message is the id + 1 of a signature
    # the client has cached, or 0 and the whole signature. A partly filtered message names the
    # characters it hides, as a BitSet (its longs).
    "minecraft:player_chat": Schema(
        global_index=VAR_INT,
        sender=UUID,
        index=VAR_INT,
        signature=PrefixedOptional(_SIGNATURE),
        message=String(_MESSAGE_MAX),
        timestamp=LONG,
        salt=LONG,
        previous_messages=PrefixedArray(Holder(_SIGNATURE), max_length=20),
        unsigned_content=PrefixedOptional(TEXT_COMPONENT),
        filter=Tagged(
            "type",
            "bits",
            [
                ("pass_through", None),
                ("fully_filtered", None),
                ("partially_filtered", PrefixedArray(LONG)),
            ],
        ),
        **_CHAT_TYPE_BOUND,
    ),
    # Disguised Chat Message: a message with no sender to check, such as one a command says for
    # the server.
    "minecraft:disguised_chat": Schema(message=TEXT_COMPONENT, **_CHAT_TYPE_BOUND),
}
