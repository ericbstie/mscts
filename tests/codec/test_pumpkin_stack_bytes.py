"""Bytes Pumpkin sent for a stack, against `SLOT`: why the Pumpkin record calls them malformed."""

import pytest
from support.gives import read_slots

from mscts.codec.wire import WireError

PUMPKIN_INTANGIBLE = bytes.fromhex("00 5a 0024  01 f107 01 00 16")
"""Pumpkin 26.3's `container_set_slot` for `arrow[intangible_projectile={}]`, as run: the
component (22) with no value. It has no network codec of its own, so vanilla sends its
persistent codec's NBT, the empty compound `0a 00` (docs/research/2026-09-30-item-stacks.md)."""


def test_pumpkins_intangible_projectile_lacks_the_nbt_vanilla_sends() -> None:
    with pytest.raises(WireError, match="intangible_projectile: NBT"):
        read_slots([PUMPKIN_INTANGIBLE])
    (slot,) = read_slots([PUMPKIN_INTANGIBLE + bytes.fromhex("0a 00")])
    assert slot["item"]["components"]["added"][0]["type"] == "minecraft:intangible_projectile"
