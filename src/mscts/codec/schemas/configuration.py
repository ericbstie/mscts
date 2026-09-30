"""Configuration-state schemas.

Field layouts: minecraft.wiki `Java_Edition_protocol/Packets`, revision 3790659
(2026-09-23, "26.3, protocol 777"), raw wikitext. Checked against the 26.3 jar with
`javap` (the packets' `STREAM_CODEC`s: e.g. the client lists at most 64 known packs).

Only what the join needs has a schema; the rest (resource packs, cookies, dialogs, server
links, report details, transfer, reset chat, ping) stays raw, compared by payload.
`update_tags` has a full schema: it is small to declare and decodes strictly.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from mscts.codec.schema import (
    BOOL,
    BYTE,
    IDENTIFIER,
    LONG,
    NBT,
    REST,
    VAR_INT,
    PrefixedArray,
    PrefixedOptional,
    Schema,
    String,
)
from mscts.codec.wire import Reader, WireError, Writer

_UNSIGNED_BYTE_MAX = 0xFF


@dataclass(frozen=True, slots=True)
class _UnsignedByte:
    """Unsigned Byte: 0 to 255 (the wiki's type; `FriendlyByteBuf.readUnsignedByte`)."""

    def read(self, reader: Reader) -> int:
        return reader.raw(1)[0]

    def write(self, writer: Writer, value: object) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            msg = f"expected an int, got {type(value).__name__}"
            raise WireError(msg)
        if not 0 <= value <= _UNSIGNED_BYTE_MAX:
            msg = f"{value} out of range for an Unsigned Byte"
            raise WireError(msg)
        writer.raw(bytes([value]))


_KNOWN_PACK = Schema(namespace=String(32767), id=String(32767), version=String(32767))

_CLIENT_KNOWN_PACKS_MAX = 64
"""`ServerboundSelectKnownPacks` reads `ByteBufCodecs.list(64)`; the server's list is unbounded."""

_KEEP_ALIVE = Schema(keep_alive_id=LONG)

# Plugin Message, both ways: the data's layout depends on the channel (minecraft:brand
# holds a String), so it is kept as the packet's remaining bytes.
_PLUGIN_MESSAGE = Schema(channel=IDENTIFIER, data=REST)

_LOCALE_MAX = 16
"""`ClientInformation` reads the language with `readUtf(16)` (26.3 javap)."""

SERVERBOUND: Mapping[str, Schema] = {
    # Client Information. The enums are VarInt ids (`ByteBufCodecs.idMapper`, 26.3 javap).
    "minecraft:client_information": Schema(
        locale=String(_LOCALE_MAX),
        view_distance=BYTE,
        chat_mode=VAR_INT,  # 0 full, 1 system (commands only), 2 hidden
        chat_colors=BOOL,
        displayed_skin_parts=_UnsignedByte(),  # bit 0 cape, 1 jacket, 2-3 sleeves, 4-5 legs, 6 hat
        main_hand=VAR_INT,  # 0 left, 1 right
        enable_text_filtering=BOOL,
        allow_server_listings=BOOL,
        particle_status=VAR_INT,  # 0 all, 1 decreased, 2 minimal
    ),
    "minecraft:custom_payload": _PLUGIN_MESSAGE,
    "minecraft:finish_configuration": Schema(),  # Acknowledge Finish Configuration: to play
    "minecraft:keep_alive": _KEEP_ALIVE,  # echoes the clientbound keep_alive_id
    "minecraft:select_known_packs": Schema(
        known_packs=PrefixedArray(_KNOWN_PACK, max_length=_CLIENT_KNOWN_PACKS_MAX)
    ),
    "minecraft:accept_code_of_conduct": Schema(),
}

CLIENTBOUND: Mapping[str, Schema] = {
    "minecraft:custom_payload": _PLUGIN_MESSAGE,
    "minecraft:disconnect": Schema(reason=NBT),  # a text component, as NBT
    "minecraft:finish_configuration": Schema(),  # the next frame is in play
    "minecraft:keep_alive": _KEEP_ALIVE,
    "minecraft:registry_data": Schema(
        registry_id=IDENTIFIER,
        entries=PrefixedArray(Schema(entry_id=IDENTIFIER, data=PrefixedOptional(NBT))),
    ),
    "minecraft:update_enabled_features": Schema(feature_flags=PrefixedArray(IDENTIFIER)),
    "minecraft:update_tags": Schema(
        tagged_registries=PrefixedArray(
            Schema(
                registry=IDENTIFIER,
                tags=PrefixedArray(Schema(tag_name=IDENTIFIER, entries=PrefixedArray(VAR_INT))),
            )
        )
    ),
    "minecraft:select_known_packs": Schema(known_packs=PrefixedArray(_KNOWN_PACK)),
    "minecraft:code_of_conduct": Schema(code_of_conduct=String(32767)),
}
