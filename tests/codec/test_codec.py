import json
from collections.abc import Iterator
from importlib import resources

import pytest

from mscts.codec.packets import Codec, CodecError, Direction, State, UnknownPacketError

CODEC = Codec.load("26.3")

KNOWN_IDS = [
    (State.HANDSHAKE, Direction.SERVERBOUND, "minecraft:intention", 0),
    (State.STATUS, Direction.CLIENTBOUND, "minecraft:status_response", 0),
    (State.STATUS, Direction.CLIENTBOUND, "minecraft:pong_response", 1),
    (State.STATUS, Direction.SERVERBOUND, "minecraft:status_request", 0),
    (State.STATUS, Direction.SERVERBOUND, "minecraft:ping_request", 1),
]


@pytest.mark.parametrize(("state", "direction", "name", "packet_id"), KNOWN_IDS)
def test_packet_id_of_known_packet(
    state: State, direction: Direction, name: str, packet_id: int
) -> None:
    assert CODEC.packet_id(state, direction, name) == packet_id


@pytest.mark.parametrize(("state", "direction", "name", "packet_id"), KNOWN_IDS)
def test_packet_name_of_known_id(
    state: State, direction: Direction, name: str, packet_id: int
) -> None:
    assert CODEC.packet_name(state, direction, packet_id) == name


def _report_entries() -> Iterator[tuple[State, Direction, str, int]]:
    """Walk the committed packet report independently of the Codec's own loader."""
    resource = resources.files("mscts.codec").joinpath("data", "26.3", "packets.json")
    report: object = json.loads(resource.read_text(encoding="utf-8"))
    assert isinstance(report, dict)
    for state, by_direction in report.items():
        assert isinstance(by_direction, dict)
        for direction, by_name in by_direction.items():
            assert isinstance(by_name, dict)
            for name, entry in by_name.items():
                assert isinstance(entry, dict)
                for key, packet_id in entry.items():
                    assert key == "protocol_id"
                    assert isinstance(packet_id, int)
                    yield State(state), Direction(direction), str(name), packet_id


def test_every_report_entry_maps_name_to_id_and_back() -> None:
    entries = list(_report_entries())
    assert len(entries) == 260  # 1 + 2 + 2 + 6 + 5 + 21 + 10 + 144 + 69
    for state, direction, name, packet_id in entries:
        assert CODEC.packet_id(state, direction, name) == packet_id
        assert CODEC.packet_name(state, direction, packet_id) == name


@pytest.mark.parametrize(
    ("state", "direction", "name"),
    [
        (State.STATUS, Direction.SERVERBOUND, "minecraft:no_such_packet"),
        (State.HANDSHAKE, Direction.CLIENTBOUND, "minecraft:intention"),  # wrong direction
        (State.LOGIN, Direction.SERVERBOUND, "minecraft:intention"),  # wrong state
    ],
)
def test_packet_id_of_unknown_name_raises(state: State, direction: Direction, name: str) -> None:
    with pytest.raises(UnknownPacketError, match=f"{state} {direction} {name}"):
        CODEC.packet_id(state, direction, name)


@pytest.mark.parametrize(
    ("direction", "count"),
    [(Direction.CLIENTBOUND, 144), (Direction.SERVERBOUND, 69)],
)
def test_play_ids_are_dense_up_to_the_26_3_packet_count(direction: Direction, count: int) -> None:
    for packet_id in range(count):
        CODEC.packet_name(State.PLAY, direction, packet_id)
    with pytest.raises(UnknownPacketError, match=f"play {direction} {count:#04x}"):
        CODEC.packet_name(State.PLAY, direction, count)


def test_packet_name_of_negative_id_raises() -> None:
    with pytest.raises(UnknownPacketError):
        CODEC.packet_name(State.STATUS, Direction.CLIENTBOUND, -1)


def test_unknown_packet_error_is_a_codec_error() -> None:
    assert issubclass(UnknownPacketError, CodecError)
