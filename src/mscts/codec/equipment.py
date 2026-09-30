"""Equipment: the slots of `set_equipment`, each with an item stack.

Pinned with `javap` on `ClientboundSetEquipmentPacket` (a do-while: a slot byte whose top bit says
another slot follows, then an optional item stack) and on `EquipmentSlot` (eight constants, whose
ordinals are the slot ids). The vanilla client takes the low 7 bits as an index into the slots
and fails on one past the last, so the Codec refuses it too.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from mscts.codec.item_stack import PENDING_ITEM_STACK
from mscts.codec.schema import WireType
from mscts.codec.wire import Reader, WireError, Writer

SLOTS = ("mainhand", "offhand", "feet", "legs", "chest", "head", "body", "saddle")
"""The equipment slots of 26.3, in ordinal order: the position is the slot id."""

_MORE = 0x80
_SLOT_MASK = 0x7F
_KEYS = ("slot", "item")


@dataclass(frozen=True, slots=True)
class EquipmentList:
    """One or more slots, each a slot byte then the item of `item`.

    Its value is a list of `{"slot": name, "item": item value}`, in wire order. The slot byte
    holds the slot id, plus 0x80 on every entry but the last, so the list is never empty.
    """

    item: WireType[object]

    def read(self, reader: Reader) -> list[dict[str, object]]:
        """Consume slots until one whose slot byte has no top bit, naming the failing slot."""
        equipment: list[dict[str, object]] = []
        while True:
            position = len(equipment)
            try:
                flagged = reader.byte()  # signed: the masks below still see the two's complement
            except WireError as exc:
                msg = f"{position}: slot: {exc}"
                raise WireError(msg) from exc
            slot_id = flagged & _SLOT_MASK
            if slot_id >= len(SLOTS):
                msg = f"{position}: slot: unknown id {slot_id}"
                raise WireError(msg)
            try:
                item = self.item.read(reader)
            except WireError as exc:
                msg = f"{position}: item: {exc}"
                raise WireError(msg) from exc
            equipment.append({"slot": SLOTS[slot_id], "item": item})
            if not flagged & _MORE:
                return equipment

    def write(self, writer: Writer, value: object) -> None:
        """Append a non-empty list or tuple of `{"slot", "item"}` mappings."""
        if not isinstance(value, list | tuple):
            msg = f"expected a list or tuple, got {type(value).__name__}"
            raise WireError(msg)
        if not value:
            msg = "needs at least one slot"
            raise WireError(msg)
        for position, entry in enumerate(value):
            try:
                self._write_entry(writer, entry, more=position < len(value) - 1)
            except WireError as exc:
                msg = f"{position}: {exc}"
                raise WireError(msg) from exc

    def _write_entry(self, writer: Writer, entry: object, *, more: bool) -> None:
        if not isinstance(entry, Mapping):
            msg = f"expected a mapping, got {type(entry).__name__}"
            raise WireError(msg)
        given = {str(key): item for key, item in entry.items()}
        problems = [f"missing key {key}" for key in _KEYS if key not in given]
        problems += [f"unexpected key {key}" for key in sorted(given) if key not in _KEYS]
        if problems:
            raise WireError("; ".join(problems))
        name = given["slot"]
        if name not in SLOTS:
            msg = f"slot: unknown {name!r}"
            raise WireError(msg)
        writer.raw(bytes([SLOTS.index(name) | (_MORE if more else 0)]))
        try:
            self.item.write(writer, given["item"])
        except WireError as exc:
            msg = f"item: {exc}"
            raise WireError(msg) from exc


EQUIPMENT: WireType[list[dict[str, object]]] = EquipmentList(PENDING_ITEM_STACK)
"""The equipment of `set_equipment`. Its items are optional item stacks, which refuse until #19."""
