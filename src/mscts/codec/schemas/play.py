"""Play-state schemas.

Field layouts: minecraft.wiki `Java_Edition_protocol/Packets`, revision 3790659
(2026-09-23, "26.3, protocol 777"), raw wikitext.

Only what the Bot's own handling needs has a schema; every other play packet stays raw,
compared by payload.
"""

from collections.abc import Mapping

from mscts.codec.schema import Schema

SERVERBOUND: Mapping[str, Schema] = {
    "minecraft:configuration_acknowledged": Schema(),  # Acknowledge Configuration
}

CLIENTBOUND: Mapping[str, Schema] = {
    "minecraft:start_configuration": Schema(),  # the next frame is in configuration
}
