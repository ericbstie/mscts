"""Helpers for building item stack values and the bytes of a stack with one component."""

NO_COMPONENTS: dict[str, object] = {"added": [], "removed": []}

_ITEM = 55  # an arbitrary item id: the codec cannot tell a valid one from an invalid one


def stack(count: int, item: int, **components: object) -> dict[str, object]:
    """A stack of `count` of item id `item` with `components` added by (unprefixed) name."""
    added = [{"type": f"minecraft:{name}", "value": value} for name, value in components.items()]
    return {"count": count, "item": item, "components": {"added": added, "removed": []}}


def stack_with_component(type_id: int, payload: str) -> bytes:
    """The bytes of one of item 55 with one component added: its type id, then `payload` (hex)."""
    return bytes.fromhex(f"01 {_ITEM:02x} 01 00 {type_id:02x} {payload}")
