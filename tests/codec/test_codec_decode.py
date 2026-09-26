import pytest

from mscts.codec.packets import (
    Codec,
    CodecError,
    Direction,
    Packet,
    State,
    UnknownPacketError,
    undecodable_frame,
)
from mscts.codec.schema import LONG, Schema

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


def test_a_decoded_packet_has_no_decode_error() -> None:
    assert CODEC.decode(State.PLAY, Direction.CLIENTBOUND, bytes.fromhex("2a")).decode_error is None


# Audit H3: a frame the Codec rejects is still recorded, as a Packet that keeps its bytes
# and says why, so a Candidate's malformed packet becomes evidence, never a silent gap.
SCHEMA_CODEC = Codec(
    {(State.PLAY, Direction.CLIENTBOUND): {"test:long": 0x2A}},
    schemas={(State.PLAY, Direction.CLIENTBOUND): {"test:long": Schema(value=LONG)}},
)


def test_undecodable_keeps_the_name_id_and_payload_of_a_packet_that_does_not_fit() -> None:
    data = bytes.fromhex("2a 0000000000000001 ff")  # one trailing byte
    with pytest.raises(CodecError) as raised:
        SCHEMA_CODEC.decode(State.PLAY, Direction.CLIENTBOUND, data)
    error = str(raised.value)
    assert SCHEMA_CODEC.undecodable(State.PLAY, Direction.CLIENTBOUND, data, error) == Packet(
        state=State.PLAY,
        direction=Direction.CLIENTBOUND,
        name="test:long",
        packet_id=0x2A,
        payload=bytes.fromhex("0000000000000001 ff"),
        fields=None,
        decode_error="play clientbound test:long: 1 unconsumed byte(s) remain",
    )


def test_undecodable_names_an_unknown_id_by_state_and_id() -> None:
    packet = CODEC.undecodable(State.PLAY, Direction.CLIENTBOUND, bytes.fromhex("2b 01"), "why")
    assert (packet.name, packet.packet_id, packet.payload) == ("unknown:play:0x2b", 0x2B, b"\x01")
    assert (packet.fields, packet.decode_error) == (None, "why")


@pytest.mark.parametrize("data", ["", "80", "8080808080"])
def test_undecodable_keeps_every_byte_when_the_packet_id_is_unreadable(data: str) -> None:
    packet = CODEC.undecodable(State.LOGIN, Direction.CLIENTBOUND, bytes.fromhex(data), "why")
    assert (packet.name, packet.packet_id, packet.payload) == (
        "corrupt:login",
        -1,
        bytes.fromhex(data),
    )


def test_undecodable_frame_keeps_the_bytes_that_could_not_be_framed() -> None:
    packet = undecodable_frame(
        State.CONFIGURATION, Direction.CLIENTBOUND, bytes.fromhex("808080"), "why"
    )
    assert packet == Packet(
        state=State.CONFIGURATION,
        direction=Direction.CLIENTBOUND,
        name="corrupt:configuration",
        packet_id=-1,
        payload=bytes.fromhex("808080"),
        fields=None,
        decode_error="why",
    )
