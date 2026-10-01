"""Round trips of clientbound play packets of Target 26.3, for the schema tests."""

from collections.abc import Mapping

from mscts.codec.packets import Codec, Direction, State
from mscts.codec.wire import Writer

CODEC = Codec.load("26.3")
CLIENTBOUND = Direction.CLIENTBOUND


def frame(name: str, payload: str) -> bytes:
    """The data of a frame of play packet `name`: its packet id, then `payload` (hex)."""
    packet_id = Writer().var_int(CODEC.packet_id(State.PLAY, CLIENTBOUND, name)).to_bytes()
    return packet_id + bytes.fromhex(payload)


def round_trip(name: str, fields: Mapping[str, object], payload: str) -> None:
    """The packet `name`'s payload (hex, after the packet id) decodes to `fields` and back."""
    data = frame(name, payload)
    assert CODEC.encode(State.PLAY, CLIENTBOUND, name, fields) == data
    packet = CODEC.decode(State.PLAY, CLIENTBOUND, data)
    assert (packet.name, packet.fields) == (name, fields)
