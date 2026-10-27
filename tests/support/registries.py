"""`registry_data` packets for the Comparison tests."""

from collections.abc import Sequence

from mscts.codec.packets import Packet, State
from support.play import CLIENTBOUND, CODEC


def registry(name: str, size: int, *, first: int = 0) -> Packet:
    """A decoded `registry_data` for registry `name` with `size` entries and no data.

    The entries are `minecraft:entry_<n>`, n counting from `first`.
    """
    return registry_of(name, [f"minecraft:entry_{index}" for index in range(first, first + size)])


def registry_of(name: str, entry_ids: Sequence[str]) -> Packet:
    """A decoded `registry_data` for registry `name` with the entries `entry_ids` and no data."""
    fields = {
        "registry_id": name,
        "entries": [{"entry_id": entry_id, "data": None} for entry_id in entry_ids],
    }
    encoded = CODEC.encode(State.CONFIGURATION, CLIENTBOUND, "minecraft:registry_data", fields)
    return CODEC.decode(State.CONFIGURATION, CLIENTBOUND, encoded)
