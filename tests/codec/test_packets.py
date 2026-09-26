from dataclasses import FrozenInstanceError

import pytest

from mscts.codec.packets import Direction, Packet, State


def test_state_values_match_packet_report_keys() -> None:
    assert [state.value for state in State] == [
        "handshake",
        "status",
        "login",
        "configuration",
        "play",
    ]


def test_direction_values_match_packet_report_keys() -> None:
    assert [direction.value for direction in Direction] == ["clientbound", "serverbound"]


def _status_response() -> Packet:
    return Packet(
        state=State.STATUS,
        direction=Direction.CLIENTBOUND,
        name="minecraft:status_response",
        packet_id=0,
        payload=b"\x02{}",
        fields={"json_response": "{}"},
    )


def test_packet_holds_what_it_was_built_with() -> None:
    packet = _status_response()
    assert packet.state is State.STATUS
    assert packet.direction is Direction.CLIENTBOUND
    assert packet.name == "minecraft:status_response"
    assert packet.packet_id == 0
    assert packet.payload == b"\x02{}"
    assert packet.fields == {"json_response": "{}"}


@pytest.mark.parametrize(
    "attribute", ["state", "direction", "name", "packet_id", "payload", "fields", "decode_error"]
)
def test_packet_is_frozen(attribute: str) -> None:
    packet = _status_response()
    with pytest.raises(FrozenInstanceError):
        setattr(packet, attribute, None)
