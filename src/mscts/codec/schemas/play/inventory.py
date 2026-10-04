"""Play-state schemas for containers: what the server shows of them, and the client's clicks.

Field layouts: minecraft.wiki `Java_Edition_protocol/Packets`, revision 3810839
(2026-10-01, "26.3, protocol 777"), raw wikitext, checked against the 26.3 client jar with
`javap` (#28): `ClientboundOpenScreenPacket`, `ClientboundContainerSetContentPacket`,
`ClientboundContainerSetSlotPacket`, `ClientboundContainerSetDataPacket`,
`ClientboundContainerClosePacket`, `ClientboundSetCursorItemPacket`,
`ClientboundSetPlayerInventoryPacket`, `ClientboundMountScreenOpenPacket`,
`ServerboundContainerClickPacket` and `ServerboundContainerClosePacket`. They agree.

A window id is a VarInt in every packet (`ByteBufCodecs.CONTAINER_ID`): 0 is the player's own
inventory. A click's mode is read leniently (`idMapper`, an unknown id is a pickup), so it is a
plain integer: 0 pickup, 1 quick move, 2 swap, 3 clone, 4 throw, 5 quick craft, 6 pickup all.
"""

from collections.abc import Mapping

from mscts.codec.items import HASHED_SLOT, SLOT
from mscts.codec.schema import BYTE, ENTITY_ID_INT, SHORT, VAR_INT, PrefixedArray, Schema
from mscts.codec.shapes import ENUM, REGISTRY_ID, TEXT_COMPONENT

_CHANGED_SLOTS_MAX = 128
"""`ServerboundContainerClickPacket.MAX_SLOT_COUNT`: the most changed slots one click carries."""

SERVERBOUND: Mapping[str, Schema] = {
    # Click Container: the window, the last state id the client received, the slot clicked
    # (-999 is outside the window), the button and the mode, then what the client predicts:
    # each slot it changed, as a hashed stack, and the stack left on the cursor.
    "minecraft:container_click": Schema(
        window_id=VAR_INT,
        state_id=VAR_INT,
        slot=SHORT,
        button=BYTE,
        mode=ENUM,
        changed_slots=PrefixedArray(
            Schema(slot=SHORT, item=HASHED_SLOT), max_length=_CHANGED_SLOTS_MAX
        ),
        carried_item=HASHED_SLOT,
    ),
    # Close Container: the window the player closed.
    "minecraft:container_close": Schema(window_id=VAR_INT),
}

CLIENTBOUND: Mapping[str, Schema] = {
    # Open Screen: the new window's id, its menu type (a `minecraft:menu` registry id) and
    # its title.
    "minecraft:open_screen": Schema(
        window_id=VAR_INT, window_type=REGISTRY_ID, window_title=TEXT_COMPONENT
    ),
    # Open Horse Screen: a mount's inventory as the new window, the columns of its chest (0 for
    # none) and the mount's entity id, an Int.
    "minecraft:mount_screen_open": Schema(
        window_id=VAR_INT, inventory_columns=VAR_INT, entity_id=ENTITY_ID_INT
    ),
    # Set Container Content: every slot of the window, in slot order, and the cursor's stack.
    "minecraft:container_set_content": Schema(
        window_id=VAR_INT, state_id=VAR_INT, slot_data=PrefixedArray(SLOT), carried_item=SLOT
    ),
    # Set Container Slot: one slot of the window.
    "minecraft:container_set_slot": Schema(
        window_id=VAR_INT, state_id=VAR_INT, slot=SHORT, slot_data=SLOT
    ),
    # Set Container Property: one of the window's numbers (a furnace's progress, ...).
    "minecraft:container_set_data": Schema(window_id=VAR_INT, property=SHORT, value=SHORT),
    # Close Container: the server closed the window.
    "minecraft:container_close": Schema(window_id=VAR_INT),
    # Set Cursor Item: the stack the cursor holds.
    "minecraft:set_cursor_item": Schema(slot_data=SLOT),
    # Set Player Inventory Slot: one slot of the player's inventory by its inventory index
    # (0 to 8 the hotbar, 9 to 35 the rest, 36 to 39 the armor, 40 the off hand, 41 the body,
    # 42 the saddle), whatever window is open.
    "minecraft:set_player_inventory": Schema(slot=VAR_INT, slot_data=SLOT),
}
