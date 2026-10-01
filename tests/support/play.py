"""Round trips of clientbound play packets of Target 26.3, for the schema tests."""

from collections.abc import Mapping

import pytest

from mscts.codec.packets import Codec, CodecError, Direction, State
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


def decode_error(name: str, payload: str) -> str:
    """Why the Codec refuses `payload` (hex) as packet `name`."""
    with pytest.raises(CodecError) as caught:
        CODEC.decode(State.PLAY, CLIENTBOUND, frame(name, payload))
    return str(caught.value)


def encode_error(name: str, fields: Mapping[str, object]) -> str:
    """Why the Codec refuses to encode `fields` as packet `name`."""
    with pytest.raises(CodecError) as caught:
        CODEC.encode(State.PLAY, CLIENTBOUND, name, fields)
    return str(caught.value)
