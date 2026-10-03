"""Play-state schemas for what the client sends as its player moves.

Field layouts: minecraft.wiki `Java_Edition_protocol/Packets`, revision 3810839
(2026-10-01, "26.3, protocol 777"), raw wikitext. Checked against the 26.3 client jar with
`javap`: `ServerboundMovePlayerPacket` and its `Pos`, `PosRot`, `Rot` and `StatusOnly`
(`packFlags`: bit 0 on ground, bit 1 horizontal collision, one byte),
`ServerboundPlayerCommandPacket` (`writeEnum` of 7 actions), `Input`'s stream codec (one
byte) and `ServerboundClientTickEndPacket` (`StreamCodec.unit`).
"""

from collections.abc import Mapping

from mscts.codec.schema import DOUBLE, ENTITY_ID, FLOAT, UBYTE, VAR_INT, Schema
from mscts.codec.shapes import OrdinalEnum

_ACTIONS = 7
"""`ServerboundPlayerCommandPacket.Action`: STOP_SLEEPING 0, START_SPRINTING 1, STOP_SPRINTING 2,
START_RIDING_JUMP 3, STOP_RIDING_JUMP 4, OPEN_INVENTORY 5, START_FALL_FLYING 6."""

SERVERBOUND: Mapping[str, Schema] = {
    # The four movement packets. Flags: bit 0 on ground, bit 1 horizontal collision.
    "minecraft:move_player_pos": Schema(x=DOUBLE, y=DOUBLE, z=DOUBLE, flags=UBYTE),
    "minecraft:move_player_pos_rot": Schema(
        x=DOUBLE, y=DOUBLE, z=DOUBLE, yaw=FLOAT, pitch=FLOAT, flags=UBYTE
    ),
    "minecraft:move_player_rot": Schema(yaw=FLOAT, pitch=FLOAT, flags=UBYTE),
    "minecraft:move_player_status_only": Schema(flags=UBYTE),
    # Player Command. The client sends its own entity id; the jump boost is 0 but for a
    # horse's jump.
    "minecraft:player_command": Schema(
        entity_id=ENTITY_ID, action=OrdinalEnum(_ACTIONS), jump_boost=VAR_INT
    ),
    # Player Input: the keys held. Bit 0 forward, 1 backward, 2 left, 3 right, 4 jump,
    # 5 sneak, 6 sprint.
    "minecraft:player_input": Schema(flags=UBYTE),
    "minecraft:client_tick_end": Schema(),  # the client has sent all of one tick
}
