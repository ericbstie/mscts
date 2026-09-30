"""Test cases: every compared field has a name built from its packet and its path (#8)."""

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from mscts.codec.packets import Codec, Packet, State
from mscts.compare import Divergence, Observability, compare
from mscts.compare import test_case as case_name
from tests.compare.build import CLIENTBOUND, SERVERBOUND, packet, transcript

ROOT = Path(__file__).resolve().parents[2]
PACKETS_JSON = ROOT / "src/mscts/codec/data/26.3/packets.json"
CODEC = Codec.load("26.3")

STATUS, LOGIN, CONFIGURATION, PLAY = State.STATUS, State.LOGIN, State.CONFIGURATION, State.PLAY
STATUS_RESPONSE = "minecraft:status_response"


@dataclass(frozen=True, slots=True)
class Case:
    state: State
    packet: str
    path: str | None
    name: str


CASES = {
    # 1. The packet id without `minecraft:`, then the path, keys joined with dots.
    "field": Case(PLAY, "minecraft:set_health", "food", "set_health.food"),
    "nested-field": Case(PLAY, "minecraft:login", "spawn.dimension", "login.spawn.dimension"),
    "non-identifier-key": Case(PLAY, "minecraft:set_health", 'm["a.b"]', 'set_health.m["a.b"]'),
    "non-identifier-first-key": Case(PLAY, "minecraft:set_health", '[""].x', 'set_health[""].x'),
    "other-namespace": Case(PLAY, "test:entity", "x", "test:entity.x"),
    # The status response's only field is its JSON text: its paths start inside the JSON.
    "status-json": Case(
        STATUS, STATUS_RESPONSE, "json_response.description", "status_response.description"
    ),
    "status-json-nested": Case(
        STATUS, STATUS_RESPONSE, "json_response.players.max", "status_response.players.max"
    ),
    "status-json-odd-key": Case(
        STATUS, STATUS_RESPONSE, 'json_response["a b"]', 'status_response["a b"]'
    ),
    "json-field-elsewhere": Case(
        PLAY, "minecraft:set_health", "json_response.x", "set_health.json_response.x"
    ),
    # 2. List elements share one test case.
    "list-element": Case(
        STATUS,
        STATUS_RESPONSE,
        "json_response.players.sample[0].name",
        "status_response.players.sample[].name",
    ),
    "list-of-lists": Case(PLAY, "minecraft:set_health", "a[1][12].b", "set_health.a[][].b"),
    "status-json-list": Case(STATUS, STATUS_RESPONSE, "json_response[3]", "status_response[]"),
    # 4. A packet compared as a whole: by payload, missing or unexpected.
    "whole-packet": Case(PLAY, "minecraft:hurt_animation", None, "hurt_animation"),
    "whole-json-text": Case(STATUS, STATUS_RESPONSE, "json_response", "status_response"),
    # 5. A packet id the Target has in more than one State starts with the State.
    "shared-whole": Case(CONFIGURATION, "minecraft:keep_alive", None, "configuration:keep_alive"),
    "shared-field": Case(PLAY, "minecraft:keep_alive", "id", "play:keep_alive.id"),
    "shared-with-status": Case(
        STATUS, "minecraft:pong_response", "timestamp", "status:pong_response.timestamp"
    ),
    "shared-by-three": Case(LOGIN, "minecraft:cookie_request", "key", "login:cookie_request.key"),
    "shared-list": Case(
        CONFIGURATION,
        "minecraft:update_tags",
        "tagged_registries[3].tags[0].entries[5]",
        "configuration:update_tags.tagged_registries[].tags[].entries[]",
    ),
}


@pytest.mark.parametrize("case", CASES.values(), ids=CASES.keys())
def test_a_test_case_is_named_after_its_packet_and_field(case: Case) -> None:
    assert case_name(case.state, case.packet, case.path) == case.name


def test_repeated_messages_and_list_elements_share_their_test_case() -> None:
    names = {
        case_name(PLAY, "minecraft:set_health", path) for path in ("a[0].b", "a[1].b", "a[99].b")
    }
    assert names == {"set_health.a[].b"}


def test_exactly_the_packet_ids_of_more_than_one_state_start_with_the_state() -> None:
    # Checked against every clientbound packet of the Target, so no hand-made list can pass.
    report = json.loads(PACKETS_JSON.read_text())
    states: dict[str, list[State]] = {}
    for state, by_direction in report.items():
        for name in by_direction.get("clientbound", {}):
            states.setdefault(name, []).append(State(state))
    prefixed = 0
    for name, where in states.items():
        for state in where:
            bare = name.removeprefix("minecraft:")
            expected = f"{state}:{bare}" if len(where) > 1 else bare
            assert case_name(state, name, None) == expected
            prefixed += len(where) > 1
    assert prefixed >= 30  # keep_alive, disconnect, custom_payload, pong_response, ...


@pytest.mark.parametrize("path", ["", "a..b", "[0]", "a[01]", 'a["b"]', "a[-1]"])
def test_a_path_not_spelled_as_divergence_paths_are_is_refused(path: str) -> None:
    with pytest.raises(ValueError, match="minecraft:set_health"):
        case_name(PLAY, "minecraft:set_health", path)


# Each Divergence names the test case it was found in.


def _status(json_response: str) -> Packet:
    fields = {"json_response": json_response}
    return CODEC.decode(
        State.STATUS, CLIENTBOUND, CODEC.encode(State.STATUS, CLIENTBOUND, STATUS_RESPONSE, fields)
    )


def _health(**fields: object) -> Packet:
    return packet("minecraft:set_health", fields=fields)


def _compared(reference: list[Packet], candidate: list[Packet]) -> list[Divergence]:
    verdict = compare(
        transcript(*(("alice", sent) for sent in reference)),
        transcript(*(("alice", sent) for sent in candidate)),
        [],
    )
    return list(verdict.divergences)


def _cases(reference: list[Packet], candidate: list[Packet]) -> list[tuple[str, str]]:
    return [(d.kind, d.test_case) for d in _compared(reference, candidate)]


def test_a_field_divergence_is_in_the_test_case_of_its_field() -> None:
    reference, candidate = _health(food=20, health=1.0), _health(food=19, health=1.0)
    assert _cases([reference], [candidate]) == [("field", "set_health.food")]


def test_every_list_element_and_every_repeated_packet_share_a_test_case() -> None:
    reference = [_health(a=[1, 2]), _health(a=[3])]
    candidate = [_health(a=[0, 0]), _health(a=[0, 4])]
    assert _cases(reference, candidate) == [("field", "set_health.a[]")] * 4


def test_a_missing_or_unexpected_packet_is_the_test_case_of_its_packet() -> None:
    hurt = packet("minecraft:hurt_animation", b"\x01")
    keep_alive = packet("minecraft:keep_alive", b"\x02", state=State.CONFIGURATION)
    assert _cases([hurt], [keep_alive]) == [
        ("missing", "hurt_animation"),
        ("unexpected", "configuration:keep_alive"),
    ]


def test_a_packet_compared_by_payload_is_the_test_case_of_its_packet() -> None:
    reference, candidate = (
        packet("minecraft:keep_alive", b"\x01"),
        packet("minecraft:keep_alive", b"\x02"),
    )
    assert _cases([reference], [candidate]) == [("field", "play:keep_alive")]


def test_a_status_difference_is_in_the_test_case_of_its_json_path() -> None:
    reference, candidate = _status('{"players":{"max":20}}'), _status('{"players":{"max":100}}')
    assert _cases([reference], [candidate]) == [("field", "status_response.players.max")]


def test_a_network_traffic_divergence_is_in_the_test_case_of_its_raw_path() -> None:
    # Vanilla sends the description as a plain string, Pumpkin as a text component.
    reference = _status('{"description":"mscts"}')
    candidate = _status('{"description":{"text":"mscts"}}')
    [divergence] = _compared([reference], [candidate])
    assert divergence.observability is Observability.NETWORK_TRAFFIC
    assert divergence.test_case == "status_response.description"


def test_a_json_spelling_is_in_the_test_case_of_the_whole_text() -> None:
    reference, candidate = _status('{"a":1,"b":2}'), _status('{"b":2,"a":1}')
    assert _cases([reference], [candidate]) == [("field", "status_response")]


def test_a_bot_on_one_side_only_is_in_no_test_case() -> None:
    hello = packet("test:hello", b"\x07", direction=SERVERBOUND)
    verdict = compare(transcript(("bob", hello)), transcript(), [])
    assert [(d.kind, d.test_case) for d in verdict.divergences] == [("bot", "")]
