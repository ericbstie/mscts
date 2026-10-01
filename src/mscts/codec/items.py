"""Item stacks: `SLOT`, the stack the server sends, and the hashed form the client sends.

Pinned with `javap` on the 26.3 server jar (docs/research/2026-09-30-item-stacks.md).
"""

from collections.abc import Mapping
from dataclasses import dataclass

from mscts.codec.components import PATCH
from mscts.codec.schema import VAR_INT, Schema
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
