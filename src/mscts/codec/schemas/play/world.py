"""World time: `set_time`, the game time and the world clocks.

Field layouts: minecraft.wiki `Java_Edition_protocol/Packets`, revision 3799543 (2026-09-27,
"26.3, protocol 777"), raw wikitext, "Update Time". Checked against the 26.3 jar with `javap` on
`ClientboundSetTimePacket.STREAM_CODEC`, `WorldClock.STREAM_CODEC` and
`ClockNetworkState.STREAM_CODEC`, and against payloads vanilla 26.3 and Pumpkin sent; all agree
(docs/research/2026-10-15-day-cycle.md).
"""

from collections.abc import Mapping

from mscts.codec.schema import FLOAT, LONG, VAR_LONG, PrefixedArray, Schema
from mscts.codec.shapes import REGISTRY_ID

CLIENTBOUND: Mapping[str, Schema] = {
    # Update Time: the game time (ticks since the world was made), then the clocks it updates,
    # each a `minecraft:world_clock` registry id (0 the overworld's, 1 the end's) and its state:
    # total ticks, the fraction of a tick, and how many ticks it moves a tick (0 while paused or
    # `advance_time` is false). The 20-tick heartbeat carries no clock; `time set` and
    # `time add` carry the one they change; a join and `gamerule advance_time` carry every one.
    # Vanilla reads the clocks into a map, so a server sends each clock once, in any order.
    "minecraft:set_time": Schema(
        game_time=LONG,
        clocks=PrefixedArray(
            Schema(clock=REGISTRY_ID, total_ticks=VAR_LONG, partial_tick=FLOAT, rate=FLOAT)
        ),
    ),
}
