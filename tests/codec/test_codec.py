import json
from collections.abc import Iterator
from importlib import resources

import pytest

from mscts.codec.packets import Codec, CodecError, Direction, State, UnknownPacketError
from mscts.codec.packets import _parse_packet_report as parse_packet_report
from mscts.target import TARGET

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


def test_load_of_a_version_without_packet_data_raises() -> None:
    with pytest.raises(CodecError, match=r"no packet data for Minecraft 0\.0"):
        Codec.load("0.0")


# Audit MD7 survivors P5 and P6: a malformed packet report is a CodecError, never a
# bool read as id 1 or an AttributeError.
@pytest.mark.parametrize(
    "report",
    [
        {"status": {"clientbound": {"minecraft:status_response": {"protocol_id": True}}}},
        {"status": {"clientbound": {"minecraft:status_response": {"protocol_id": "0"}}}},
        [],
        {"status": []},
        {"status": {"clientbound": []}},
        {"status": {"clientbound": {"minecraft:status_response": 0}}},
    ],
)
def test_a_malformed_packet_report_raises_codec_error(report: object) -> None:
    with pytest.raises(CodecError, match="packet report: expected"):
        parse_packet_report(report)


def test_codec_rejects_two_names_sharing_an_id() -> None:
    table = {(State.STATUS, Direction.CLIENTBOUND): {"test:first": 0, "test:second": 0}}
    with pytest.raises(CodecError, match="test:first and test:second share id 0x00"):
        Codec(table)


def test_for_target_loads_the_codec_of_the_targets_minecraft_version() -> None:
    codec = Codec.for_target(TARGET)
    assert codec.packet_id(State.HANDSHAKE, Direction.SERVERBOUND, "minecraft:intention") == 0
