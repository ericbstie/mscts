"""Login-state schemas.

Field layouts: minecraft.wiki `Java_Edition_protocol/Packets`, revision 3790659
(2026-09-23, "26.3, protocol 777"), raw wikitext; Game Profile from
`Java_Edition_protocol/Data_types`, revision 3763787. Checked against the 26.3 jar with
`javap` (`ClientboundLoginFinishedPacket`, `ByteBufCodecs.GAME_PROFILE`).

Only what the join needs has a schema. `login_disconnect` (a JSON text component of up
to 262 144 characters, past what String (n) allows), the encryption `hello`, and the
plugin and cookie queries stay raw, compared by payload.
"""

from collections.abc import Mapping

from mscts.codec.schema import (
    UUID,
    VAR_INT,
    PrefixedArray,
    PrefixedOptional,
    Schema,
    String,
)

GAME_PROFILE = Schema(
    uuid=UUID,
    username=String(16),
    properties=PrefixedArray(
        Schema(name=String(64), value=String(32767), signature=PrefixedOptional(String(1024))),
        max_length=16,
    ),
)
"""Game Profile (wiki Data types): a player's UUID, name, and at most 16 properties."""

SERVERBOUND: Mapping[str, Schema] = {
    "minecraft:hello": Schema(name=String(16), player_uuid=UUID),  # Login Start
    "minecraft:login_acknowledged": Schema(),  # switches to configuration
}

CLIENTBOUND: Mapping[str, Schema] = {
    "minecraft:login_compression": Schema(threshold=VAR_INT),  # Set Compression; < 0 is off
    "minecraft:login_finished": Schema(profile=GAME_PROFILE, session_id=UUID),  # Login Success
}
