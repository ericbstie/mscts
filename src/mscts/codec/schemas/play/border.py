"""World border packets: the border's size, centre, lerp and warnings.

Field layouts: the 26.3 jar with `javap` on each packet's `write` and its reading constructor
(`ClientboundInitializeBorderPacket`, `ClientboundSetBorderSizePacket`,
`ClientboundSetBorderLerpSizePacket`, `ClientboundSetBorderCenterPacket`,
`ClientboundSetBorderWarningDelayPacket` and `ClientboundSetBorderWarningDistancePacket`),
from the fact sheet of #68. The client applies them in `ClientPacketListener.handleInitializeBorder`
and the `handleSetBorder*` methods, onto its `WorldBorder`.

Each field is named after the field the packet reads it into. A size is a double; a lerp time is
a VarLong of ticks, the ticks the border has left to move, not milliseconds; the warnings are
VarInts.
"""

from collections.abc import Mapping

from mscts.codec.schema import DOUBLE, VAR_INT, VAR_LONG, Schema

CLIENTBOUND: Mapping[str, Schema] = {
    # Initialize Border: sent on a join and a respawn. The client reads it into its border:
    # `setCenter(center_x, center_z)`, then `lerpSizeBetween(old_size, new_size, lerp_time,
    # gameTime)` if `lerp_time` is above 0 and `setSize(new_size)` if not, then
    # `setAbsoluteMaxSize`, `setWarningBlocks` and `setWarningTime`.
    "minecraft:initialize_border": Schema(
        center_x=DOUBLE,
        center_z=DOUBLE,
        old_size=DOUBLE,
        new_size=DOUBLE,
        lerp_time=VAR_LONG,
        absolute_max_size=VAR_INT,
        warning_blocks=VAR_INT,
        warning_time=VAR_INT,
    ),
    # Set Border Center: `handleSetBorderCenter` calls `setCenter`.
    "minecraft:set_border_center": Schema(center_x=DOUBLE, center_z=DOUBLE),
    # Set Border Lerp Size: `handleSetBorderLerpSize` calls `lerpSizeBetween(old_size, new_size,
    # lerp_time, gameTime)`; the client's border then moves a tick at a time, as the server's.
    "minecraft:set_border_lerp_size": Schema(old_size=DOUBLE, new_size=DOUBLE, lerp_time=VAR_LONG),
    # Set Border Size: `handleSetBorderSize` calls `setSize`.
    "minecraft:set_border_size": Schema(size=DOUBLE),
    # Set Border Warning Delay: `handleSetBorderWarningDelay` calls `setWarningTime`, in ticks.
    "minecraft:set_border_warning_delay": Schema(warning_delay=VAR_INT),
    # Set Border Warning Distance: `handleSetBorderWarningDistance` calls `setWarningBlocks`.
    "minecraft:set_border_warning_distance": Schema(warning_blocks=VAR_INT),
}
