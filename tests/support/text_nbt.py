"""Network NBT for the text components the Comparison tests send (#335).

`nbt(value)` writes one unnamed root tag: a str is a String, a dict a Compound (its entries
in the dict's order), a list a List of its first element's type (End when empty), and a
`Numeric` its own type. A wrapped heterogeneous list is written as vanilla's `ListTag` does:
a list of compounds, each `{"": element}`.
"""

import struct

from mscts.codec.nbt import Numeric

_NUMBERS = {
    "byte": (1, ">b"),
    "short": (2, ">h"),
    "int": (3, ">i"),
    "long": (4, ">q"),
    "float": (5, ">f"),
    "double": (6, ">d"),
}

type Writable = str | Numeric | list[Writable] | dict[str, Writable]


def nbt(value: Writable) -> bytes:
    """`value` as one network NBT root tag: its type byte, then its payload."""
    tag_type, payload = _typed(value)
    return bytes([tag_type]) + payload


def wrapped(*elements: Writable) -> list[Writable]:
    """A list of `elements`, each in a `{"": element}` compound, as vanilla writes a mixed list."""
    return [{"": element} for element in elements]


def _typed(value: Writable) -> tuple[int, bytes]:
    if isinstance(value, str):
        encoded = value.encode()
        return 8, len(encoded).to_bytes(2, "big") + encoded
    if isinstance(value, Numeric):
        tag_type, layout = _NUMBERS[value.kind]
        return tag_type, struct.pack(layout, value.value)
    if isinstance(value, dict):
        entries = b""
        for name, item in value.items():
            tag_type, payload = _typed(item)
            encoded = name.encode()
            entries += bytes([tag_type]) + len(encoded).to_bytes(2, "big") + encoded + payload
        return 10, entries + b"\x00"
    typed = [_typed(item) for item in value]
    element_type = typed[0][0] if typed else 0
    if any(tag_type != element_type for tag_type, _ in typed):
        msg = f"a list holds one tag type: wrap the elements of {value!r}"
        raise ValueError(msg)
    return 9, bytes([element_type]) + len(typed).to_bytes(4, "big") + b"".join(
        payload for _, payload in typed
    )
