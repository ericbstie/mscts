"""Handshake-state schemas.

Field layouts: minecraft.wiki `Java_Edition_protocol/Packets`, revision
3790659 (2026-09-23, "26.3, protocol 777"), raw wikitext.
"""

from collections.abc import Mapping

from mscts.codec.schema import USHORT, VAR_INT, Schema, String

SERVERBOUND: Mapping[str, Schema] = {
    "minecraft:intention": Schema(
        protocol_version=VAR_INT,
        server_address=String(255),
        server_port=USHORT,
        intent=VAR_INT,  # 1 = status, 2 = login, 3 = transfer
    ),
}
