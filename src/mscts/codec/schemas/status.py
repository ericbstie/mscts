"""Status-state schemas.

Field layouts: minecraft.wiki `Java_Edition_protocol/Packets`, revision
3790659 (2026-09-23, "26.3, protocol 777"), raw wikitext.
"""

from collections.abc import Mapping

from mscts.codec.schema import LONG, Schema, String

SERVERBOUND: Mapping[str, Schema] = {
    "minecraft:status_request": Schema(),
    "minecraft:ping_request": Schema(timestamp=LONG),
}

CLIENTBOUND: Mapping[str, Schema] = {
    "minecraft:status_response": Schema(json_response=String(32767)),
    "minecraft:pong_response": Schema(timestamp=LONG),  # echoes ping_request's timestamp
}
