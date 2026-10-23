"""`registry_data` packets for the Comparison tests."""

from mscts.codec.packets import Packet, State
from support.play import CLIENTBOUND, CODEC


def registry(name: str, size: int, *, first: int = 0) -> Packet:
    """A decoded `registry_data` for registry `name` with `size` entries and no data.

    The entries are `minecraft:entry_<n>`, n counting from `first`.
    """
    entries = [
        {"entry_id": f"minecraft:entry_{index}", "data": None}
        for index in range(first, first + size)
    ]
    fields = {"registry_id": name, "entries": entries}
    encoded = CODEC.encode(State.CONFIGURATION, CLIENTBOUND, "minecraft:registry_data", fields)
    return CODEC.decode(State.CONFIGURATION, CLIENTBOUND, encoded)
