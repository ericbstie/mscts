"""Play-state schemas for statistics: what the barrier (`Bot.sync`) sends.

Field layouts: minecraft.wiki `Java_Edition_protocol/Packets`, revision 3790659
(2026-09-23, "26.3, protocol 777"), raw wikitext, "Client Status". Checked against the
26.3 jar with `javap`: `ServerboundClientCommandPacket` writes its `Action` with
`FriendlyByteBuf.writeEnum`, a VarInt of the ordinal.
"""

from collections.abc import Mapping

from mscts.codec.schema import VAR_INT, Schema

REQUEST_STATS = 1
"""The `client_command` action that asks for the player's statistics, which the server
answers with `award_stats` (`ServerboundClientCommandPacket$Action`: PERFORM_RESPAWN 0,
REQUEST_STATS 1, REQUEST_GAMERULE_VALUES 2; 26.3 javap)."""

SERVERBOUND: Mapping[str, Schema] = {
    # Client Status: respawn, or send the statistics, or the game rule values.
    "minecraft:client_command": Schema(action=VAR_INT),
}
