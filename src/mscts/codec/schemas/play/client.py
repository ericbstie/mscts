"""Play-state schemas for what the client tells the server about itself.

Field layouts: minecraft.wiki `Java_Edition_protocol/Packets`, revision 3790659
(2026-09-23, "26.3, protocol 777"), raw wikitext. Checked against the 26.3 jar with
`javap` (`ServerboundPlayerLoadedPacket.STREAM_CODEC` is `StreamCodec.unit`).
"""

from collections.abc import Mapping

from mscts.codec.schema import Schema

SERVERBOUND: Mapping[str, Schema] = {
    # Player Loaded: the client has loaded the world, so the server may now move, hurt and
    # hear from its player (docs/research/2026-09-26-join.md).
    "minecraft:player_loaded": Schema(),
}
