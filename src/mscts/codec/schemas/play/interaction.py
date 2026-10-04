"""Play-state schemas for what the client sends as its player digs, places and uses items.

Field layouts: minecraft.wiki `Java_Edition_protocol/Packets`, revision 3810839
(2026-10-01, "26.3, protocol 777"), raw wikitext, checked against the 26.3 client jar with
`javap`: `ServerboundPlayerActionPacket`, `ServerboundUseItemOnPacket` (`InteractionHand` and
`BlockHitResult`'s stream codecs), `ServerboundUseItemPacket`, `ServerboundSetCarriedItemPacket`,
`ServerboundPunchPacket` (`StreamCodec.unit`), `ClientboundBlockChangedAckPacket` and
`ClientboundSetHeldSlotPacket`. They agree but for one thing: the wiki lists 8 player actions
and 26.3 has 9, with `CHANGE_DESTROY_DIRECTION` at 1, so every action after it is one higher
than the wiki says (#26).

A hand and a face are read leniently (`idMapper`, or `Direction.from3DDataValue` on an
unsigned byte), so they are plain integers here: hand 0 main, 1 off; face 0 down, 1 up,
2 north, 3 south, 4 west, 5 east.
"""

from collections.abc import Mapping

from mscts.codec.schema import BOOL, FLOAT, POSITION, SHORT, UBYTE, VAR_INT, Schema
from mscts.codec.shapes import OrdinalEnum

_ACTIONS = 9
"""`ServerboundPlayerActionPacket.Action`: START_DESTROY_BLOCK 0, CHANGE_DESTROY_DIRECTION 1,
ABORT_DESTROY_BLOCK 2, STOP_DESTROY_BLOCK 3, DROP_ALL_ITEMS 4, DROP_ITEM 5, RELEASE_USE_ITEM 6,
SWAP_ITEM_WITH_OFFHAND 7, STAB 8."""

SERVERBOUND: Mapping[str, Schema] = {
    # Player Action: digging, dropping, releasing the item in use. The face is one byte here.
    "minecraft:player_action": Schema(
        action=OrdinalEnum(_ACTIONS), pos=POSITION, face=UBYTE, sequence=VAR_INT
    ),
    # Use Item On: the hand, then the block hit: the block, its face (a VarInt here), where on
    # the block (0 to 1 on each axis), whether the eyes are inside a block, and whether it hit
    # the world border.
    "minecraft:use_item_on": Schema(
        hand=VAR_INT,
        pos=POSITION,
        face=VAR_INT,
        cursor_x=FLOAT,
        cursor_y=FLOAT,
        cursor_z=FLOAT,
        inside_block=BOOL,
        world_border_hit=BOOL,
        sequence=VAR_INT,
    ),
    # Use Item: the hand and the player's rotation as it uses it.
    "minecraft:use_item": Schema(hand=VAR_INT, sequence=VAR_INT, yaw=FLOAT, pitch=FLOAT),
    # Set Held Item: the hotbar slot selected, 0 to 8.
    "minecraft:set_carried_item": Schema(slot=SHORT),
    "minecraft:punch": Schema(),  # the player swings its main hand to attack or dig
}

CLIENTBOUND: Mapping[str, Schema] = {
    # Acknowledge Block Change: the server has handled the client's actions up to `sequence`.
    "minecraft:block_changed_ack": Schema(sequence=VAR_INT),
    # Set Held Item: the server selects a hotbar slot; the client ignores one outside 0 to 8.
    "minecraft:set_held_slot": Schema(slot=VAR_INT),
}
