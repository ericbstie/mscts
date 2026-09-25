import json
from importlib import resources

from mscts.codec.packets import Direction, State


def _packet_report() -> object:
    resource = resources.files("mscts.codec").joinpath("data", "26.3", "packets.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def test_packet_report_is_package_data_keyed_by_state_and_direction() -> None:
    report = _packet_report()
    assert isinstance(report, dict)
    assert set(report) == {state.value for state in State}
    directions = {direction.value for direction in Direction}
    for by_direction in report.values():
        assert isinstance(by_direction, dict)
        assert set(by_direction) <= directions
