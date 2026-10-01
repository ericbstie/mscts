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
    BOOL,
    BYTE,
    IDENTIFIER,
    LONG,
    NBT,
    REST,
    UBYTE,
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

# Plugin Message, both ways: the data's layout depends on the channel (minecraft:brand
# holds a String), so it is kept as the packet's remaining bytes.
_PLUGIN_MESSAGE = Schema(channel=IDENTIFIER, data=REST)

_LOCALE_MAX = 16
"""`ClientInformation` reads the language with `readUtf(16)` (26.3 javap)."""

CLIENT_INFORMATION: Mapping[str, object] = {
    "locale": "en_us",  # Options.<init>: languageCode = "en_us"
    "view_distance": 12,  # renderDistance: OptionInstance(..., IntRange(2, 16 or 32), 12)
    "chat_mode": 0,  # chatVisibility: ChatVisiblity.FULL
    "chat_colors": True,  # chatColors: createBoolean("options.chat.color", true)
    "displayed_skin_parts": 0x7F,  # modelParts: EnumSet.allOf(PlayerModelPart), bits 0-6
    "main_hand": 1,  # mainHand: HumanoidArm.RIGHT
    "enable_text_filtering": False,  # Minecraft.isTextFilteringEnabled: no account, so false
    "allow_server_listings": True,  # allowServerListing: createBoolean(..., true, ...)
    "particle_status": 0,  # particles: ParticleStatus.ALL
}
"""The `client_information` a fresh vanilla client sends: `Options.buildPlayerInformation()`
on a new `options.txt` (26.3 javap; docs/research/2026-09-26-join.md, "What the client
sends by itself"). A Bot sends it after `login_finished`, as the vanilla client does."""

SERVERBOUND: Mapping[str, Schema] = {
    # Client Information. The enums are VarInt ids (`ByteBufCodecs.idMapper`, 26.3 javap).
    "minecraft:client_information": Schema(
        locale=String(_LOCALE_MAX),
        view_distance=BYTE,
        chat_mode=VAR_INT,  # 0 full, 1 system (commands only), 2 hidden
        chat_colors=BOOL,
        displayed_skin_parts=UBYTE,  # bit 0 cape, 1 jacket, 2-3 sleeves, 4-5 legs, 6 hat
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
