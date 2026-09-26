"""Configuration-state schemas.

Field layouts: minecraft.wiki `Java_Edition_protocol/Packets`, revision 3790659
(2026-09-23, "26.3, protocol 777"), raw wikitext. Checked against the 26.3 jar with
`javap` (the packets' `STREAM_CODEC`s: e.g. the client lists at most 64 known packs).

Only what the join needs has a schema; the rest (resource packs, cookies, dialogs, server
links, report details, transfer, reset chat, ping) stays raw, compared by payload.
`update_tags` has a full schema: it is small to declare and decodes strictly.
"""

from collections.abc import Mapping

from mscts.codec.schema import (
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

_KNOWN_PACK = Schema(namespace=String(32767), id=String(32767), version=String(32767))

_CLIENT_KNOWN_PACKS_MAX = 64
"""`ServerboundSelectKnownPacks` reads `ByteBufCodecs.list(64)`; the server's list is unbounded."""

_KEEP_ALIVE = Schema(keep_alive_id=LONG)

SERVERBOUND: Mapping[str, Schema] = {
    "minecraft:finish_configuration": Schema(),  # Acknowledge Finish Configuration: to play
    "minecraft:keep_alive": _KEEP_ALIVE,  # echoes the clientbound keep_alive_id
    "minecraft:select_known_packs": Schema(
        known_packs=PrefixedArray(_KNOWN_PACK, max_length=_CLIENT_KNOWN_PACKS_MAX)
    ),
    "minecraft:accept_code_of_conduct": Schema(),
}

CLIENTBOUND: Mapping[str, Schema] = {
    # Plugin Message: the data's layout depends on the channel (minecraft:brand holds a
    # String), so it is kept as the packet's remaining bytes.
    "minecraft:custom_payload": Schema(channel=IDENTIFIER, data=REST),
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
