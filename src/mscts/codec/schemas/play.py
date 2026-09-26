"""Play-state schemas.

Field layouts: minecraft.wiki `Java_Edition_protocol/Packets`, revision 3790659
(2026-09-23, "26.3, protocol 777"), raw wikitext. Checked against the 26.3 jar with
`javap` (`ClientboundLoginPacket` and `CommonPlayerSpawnInfo`,
`ClientboundPlayerPositionPacket`, `ServerboundAcceptTeleportationPacket`, the chunk batch
and keep-alive packets).

Only what the Bot's own handling needs has a schema, plus `login`, whose entity id a
Comparison will need to Mask; every other play packet stays raw, compared by payload.
"""

from collections.abc import Mapping

from mscts.codec.schema import (
    BOOL,
    DOUBLE,
    FLOAT,
    IDENTIFIER,
    INT,
    LONG,
    NBT,
    POSITION,
    VAR_INT,
    PrefixedArray,
    PrefixedOptional,
    Schema,
)

_KEEP_ALIVE = Schema(keep_alive_id=LONG)

SERVERBOUND: Mapping[str, Schema] = {
    # Confirm Teleportation: in 26.3 it echoes the pose the teleport resulted in.
    "minecraft:accept_teleportation": Schema(
        teleport_id=VAR_INT, x=DOUBLE, y=DOUBLE, z=DOUBLE, yaw=FLOAT, pitch=FLOAT
    ),
    "minecraft:chunk_batch_received": Schema(chunks_per_tick=FLOAT),
    "minecraft:configuration_acknowledged": Schema(),  # Acknowledge Configuration
    "minecraft:keep_alive": _KEEP_ALIVE,
}

CLIENTBOUND: Mapping[str, Schema] = {
    "minecraft:chunk_batch_finished": Schema(batch_size=VAR_INT),
    "minecraft:chunk_batch_start": Schema(),
    "minecraft:disconnect": Schema(reason=NBT),  # a text component, as NBT
    "minecraft:keep_alive": _KEEP_ALIVE,
    "minecraft:login": Schema(  # Login (play)
        entity_id=INT,
        is_hardcore=BOOL,
        dimension_names=PrefixedArray(IDENTIFIER),
        max_players=VAR_INT,
        view_distance=VAR_INT,
        simulation_distance=VAR_INT,
        reduced_debug_info=BOOL,
        enable_respawn_screen=BOOL,
        do_limited_crafting=BOOL,
        dimension_type=VAR_INT,
        dimension_name=IDENTIFIER,
        hashed_seed=LONG,
        game_mode=VAR_INT,
        previous_game_mode=VAR_INT,  # 0: none, else the game mode + 1
        is_debug=BOOL,
        is_flat=BOOL,
        # "Has death location", then the two Optional fields it governs: one composite.
        death_location=PrefixedOptional(
            Schema(death_dimension_name=IDENTIFIER, death_location=POSITION)
        ),
        portal_cooldown=VAR_INT,
        sea_level=VAR_INT,
        online_mode=BOOL,
        enforces_secure_chat=BOOL,
    ),
    # Synchronize Player Position. Flags is the Teleport Flags bit field (wiki Data types):
    # bit 0-2 relative x/y/z, 3 yaw, 4 pitch, 5-7 velocity x/y/z, 8 rotate velocity.
    "minecraft:player_position": Schema(
        teleport_id=VAR_INT,
        x=DOUBLE,
        y=DOUBLE,
        z=DOUBLE,
        velocity_x=DOUBLE,
        velocity_y=DOUBLE,
        velocity_z=DOUBLE,
        yaw=FLOAT,
        pitch=FLOAT,
        flags=INT,
    ),
    "minecraft:start_configuration": Schema(),  # the next frame is in configuration
}
