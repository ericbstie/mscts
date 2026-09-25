import pytest

from mscts.codec.packets import Codec, CodecError, Direction, Packet, State, UnknownPacketError

CODEC = Codec({(State.PLAY, Direction.CLIENTBOUND): {"test:raw": 0x2A}})


def test_decode_of_packet_without_schema_keeps_the_raw_payload() -> None:
    packet = CODEC.decode(State.PLAY, Direction.CLIENTBOUND, bytes.fromhex("2a 01 02 ff"))
    assert packet == Packet(
        state=State.PLAY,
        direction=Direction.CLIENTBOUND,
        name="test:raw",
        packet_id=0x2A,
        payload=bytes.fromhex("01 02 ff"),
        fields=None,
    )


def test_decode_of_packet_without_schema_accepts_an_empty_payload() -> None:
    packet = CODEC.decode(State.PLAY, Direction.CLIENTBOUND, bytes.fromhex("2a"))
    assert packet.payload == b""
    assert packet.fields is None


def test_decode_of_unknown_id_raises() -> None:
    with pytest.raises(UnknownPacketError, match="play clientbound 0x2b"):
        CODEC.decode(State.PLAY, Direction.CLIENTBOUND, bytes.fromhex("2b"))


def test_decode_of_id_in_the_wrong_direction_raises() -> None:
    with pytest.raises(UnknownPacketError, match="play serverbound 0x2a"):
        CODEC.decode(State.PLAY, Direction.SERVERBOUND, bytes.fromhex("2a"))


@pytest.mark.parametrize("data", ["", "80"])
def test_decode_without_a_complete_packet_id_raises(data: str) -> None:
    with pytest.raises(CodecError, match="packet id: VarInt truncated"):
        CODEC.decode(State.PLAY, Direction.CLIENTBOUND, bytes.fromhex(data))
