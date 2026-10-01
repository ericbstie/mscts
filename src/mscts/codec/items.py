"""Item stacks: `SLOT`, the stack the server sends, and the hashed form the client sends.

Pinned with `javap` on the 26.3 server jar (docs/research/2026-09-30-item-stacks.md).
"""

from collections.abc import Mapping
from dataclasses import dataclass

from mscts.codec.components import COMPONENT_TYPE, PATCH
from mscts.codec.schema import INT, VAR_INT, PrefixedArray, PrefixedOptional, Schema
from mscts.codec.shapes import REGISTRY_ID
from mscts.codec.wire import Reader, WireError, Writer

_STACK = Schema(count=VAR_INT, item=REGISTRY_ID, components=PATCH)
_AFTER_COUNT = Schema(item=REGISTRY_ID, components=PATCH)


@dataclass(frozen=True, slots=True)
class _Slot:
    def read(self, reader: Reader) -> dict[str, object] | None:
        count = reader.var_int()
        if count == 0:
            return None
        if count < 0:
            msg = f"count: {count} is negative (vanilla reads that as an empty stack)"
            raise WireError(msg)
        return {"count": count, **_AFTER_COUNT.read(reader)}

    def write(self, writer: Writer, value: object) -> None:
        if value is None:
            writer.var_int(0)
            return
        count = value.get("count") if isinstance(value, Mapping) else None
        if isinstance(count, int) and not isinstance(count, bool) and count < 1:
            msg = f"count: {count} is not positive: write an empty stack as None"
            raise WireError(msg)
        _STACK.write(writer, value)


SLOT = _Slot()
"""An item stack, or none (`ItemStack.OPTIONAL_STREAM_CODEC`).

On the wire: the VarInt count (0 is the empty stack, and nothing follows), the item as a registry
id, then the data component `Patch`. Its value is None for the empty stack, otherwise
`{"count": int, "item": int, "components": {"added": [...], "removed": [...]}}`.

The count is checked on write (an empty stack is None, never a count of 0) and a negative count is
refused on read: vanilla reads it as empty, which would not re-encode to the same bytes.
"""

# At most 256 of each, as `HashedPatchMap.STREAM_CODEC` limits its map and its list.
_HASHED_COMPONENTS = Schema(
    added=PrefixedArray(Schema(type=COMPONENT_TYPE, hash=INT), max_length=256),
    removed=PrefixedArray(COMPONENT_TYPE, max_length=256),
)

HASHED_SLOT = PrefixedOptional(
    Schema(item=REGISTRY_ID, count=VAR_INT, components=_HASHED_COMPONENTS)
)
"""The stack a client sends in place of a `SLOT` (`HashedStack.STREAM_CODEC`): the wire type only.

On the wire: a Bool (false is no stack, and nothing follows), the item as a registry id, the
VarInt count (item first, the other way round from a `SLOT`), the added components as a type id
and an Int hash each, then the removed type ids. Its value is None, or `{"item": int, "count": int,
"components": {"added": [{"type": name, "hash": int}, ...], "removed": [name, ...]}}`, in wire
order. The hashes are given and read back as they are: computing one is not this type's job.
"""
