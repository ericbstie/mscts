"""Block packets: single and multi-block updates, block entity data, block events and destruction.

Field layouts: minecraft.wiki `Java_Edition_protocol/Packets`, revision 3799543 (2026-09-27,
"26.3, protocol 777"), raw wikitext, checked against the 26.3 jar with `javap` on each packet's
`STREAM_CODEC`; the two agree (docs/research/2026-10-01-block-world-events.md). A block state is
its id in the global block state registry (`idMapper`, a plain VarInt, not range checked), and a
block or a block entity type is a registry id.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from mscts.codec.schema import (
    ENTITY_ID,
    LONG,
    POSITION,
    UBYTE,
    VAR_INT,
    PrefixedArray,
    Schema,
    WireType,
)
from mscts.codec.shapes import COMPOUND_TAG, REGISTRY_ID, SECTION_POSITION
from mscts.codec.wire import Reader, WireError, Writer

_COORDINATES = (("x", 8), ("z", 4), ("y", 0))
"""Each coordinate of a block in its section: its name and shift in the entry (x z y, 4 bits)."""
_COORDINATE_MAX = 15
_STATE_SHIFT = 12
_STATE_MAX = (1 << 31) - 1
_ENTRY_MAX = (_STATE_MAX << _STATE_SHIFT) | (1 << _STATE_SHIFT) - 1


def _integer(given: Mapping[str, object], name: str) -> int:
    item = given.get(name)
    if isinstance(item, bool) or not isinstance(item, int):
        msg = f"{name}: expected an int, got {type(item).__name__}"
        raise WireError(msg)
    return item


@dataclass(frozen=True, slots=True)
class _SectionBlock:
    """One block of an `section_blocks_update`: a VarLong of its state and section position.

    The VarLong is the block state id shifted left by 12, then the block's position in its section
    as x, z and y of 4 bits each (`ClientboundSectionBlocksUpdatePacket`). Vanilla reads the state
    back with an `(int)` cast, so a value above `2**43 - 1` is no entry it could have sent.
    """

    def read(self, reader: Reader) -> dict[str, int]:
        packed = reader.var_long()
        if not 0 <= packed <= _ENTRY_MAX:
            msg = f"{packed} is not a block state id << 12 and a position (0 to {_ENTRY_MAX})"
            raise WireError(msg)
        return {
            "x": packed >> 8 & _COORDINATE_MAX,
            "y": packed & _COORDINATE_MAX,
            "z": packed >> 4 & _COORDINATE_MAX,
            "state": packed >> _STATE_SHIFT,
        }

    def write(self, writer: Writer, value: object) -> None:
        # Exactly the names x, y, z and state, each an int: the Schema says what is wrong if not.
        Schema(x=LONG, y=LONG, z=LONG, state=LONG).write(Writer(), value)
        given = (
            {str(key): item for key, item in value.items()} if isinstance(value, Mapping) else {}
        )
        packed = 0
        for name, shift in _COORDINATES:
            coordinate = _integer(given, name)
            if not 0 <= coordinate <= _COORDINATE_MAX:
                msg = f"{name}: {coordinate} out of range for 0 to {_COORDINATE_MAX}"
                raise WireError(msg)
            packed |= coordinate << shift
        state = _integer(given, "state")
        if not 0 <= state <= _STATE_MAX:
            msg = f"state: {state} out of range for 0 to {_STATE_MAX}"
            raise WireError(msg)
        writer.var_long(state << _STATE_SHIFT | packed)


_SECTION_BLOCK: WireType[dict[str, int]] = _SectionBlock()

CLIENTBOUND: Mapping[str, Schema] = {
    # Block Update: the block at `pos` is now `block_state`.
    "minecraft:block_update": Schema(pos=POSITION, block_state=VAR_INT),
    # Update Section Blocks: two or more blocks of one chunk section changed in a tick. Each is
    # its position in the section (0 to 15 on each axis) and block state, in the order sent.
    "minecraft:section_blocks_update": Schema(
        section=SECTION_POSITION, blocks=PrefixedArray(_SECTION_BLOCK)
    ),
    # Block Entity Data: the type is a `minecraft:block_entity_type` id; the data an NBT compound.
    "minecraft:block_entity_data": Schema(pos=POSITION, type=REGISTRY_ID, tag=COMPOUND_TAG),
    # Block Action: what a block does (a piston extends, a note block plays). The action and its
    # parameter mean what the block says; the block is a `minecraft:block` id (not a state) and
    # comes last.
    "minecraft:block_event": Schema(
        pos=POSITION, action_id=UBYTE, action_parameter=UBYTE, block=REGISTRY_ID
    ),
    # Set Block Destroy Stage: the entity breaking the block; the stage is 0 to 9 for a crack,
    # anything else clears it.
    "minecraft:block_destruction": Schema(entity_id=ENTITY_ID, pos=POSITION, stage=UBYTE),
}
