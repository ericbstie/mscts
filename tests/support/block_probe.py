"""The block the live Control tests set, and the packet that tells a Bot it changed."""

from mscts.codec.packets import Packet
from mscts.codec.schema import POSITION
from mscts.codec.wire import Reader

BLOCK = {"x": 1, "y": -60, "z": 1}


def at_block(packet: Packet) -> bool:
    """Whether a `block_update` is for BLOCK: its payload starts with the position."""
    return POSITION.read(Reader(packet.payload)) == BLOCK
