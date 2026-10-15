"""Hermetic tests for scripts/research/time_query_lag.py: reading when `set_time` is stamped."""

import importlib.util
import time
import types
from pathlib import Path

import pytest

from mscts.codec.packets import Direction, Packet, State
from mscts.transcript import Transcript

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "research" / "time_query_lag.py"


@pytest.fixture
def lag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> types.ModuleType:
    monkeypatch.setenv("MSCTS_CACHE", str(tmp_path / "cache"))
    spec = importlib.util.spec_from_file_location("research_time_query_lag", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _set_time(game_time: int) -> Packet:
    return Packet(
        state=State.PLAY,
        direction=Direction.CLIENTBOUND,
        name="minecraft:set_time",
        packet_id=0,
        payload=game_time.to_bytes(8, "big") + b"\x00",
        fields=None,
    )


def _answer(game_time: int) -> Packet:
    """Vanilla's answer to `time query gametime`: a translated text with a Long argument."""
    content = (
        b"commands.time.query.gametime\x09\x00\x04with\x04\x00\x00\x00\x01"
        + game_time.to_bytes(8, "big")
    )
    return Packet(
        state=State.PLAY,
        direction=Direction.CLIENTBOUND,
        name="minecraft:system_chat",
        packet_id=0,
        payload=b"",
        fields={"content": content},
    )


def _transcript(*received: tuple[str, Packet]) -> Transcript:
    transcript = Transcript(group_id="lag", server="a", start_ns=time.monotonic_ns())
    for at, (bot, packet) in enumerate(received):
        transcript.record(bot, packet, t_ns=at)
    return transcript


def test_a_set_time_after_an_answer_with_its_game_time_was_stamped_before_the_tick(
    lag: types.ModuleType,
) -> None:
    transcript = _transcript(
        ("control", _answer(100)),
        ("control", _set_time(100)),
        ("control", _answer(103)),
    )
    stamps = lag.stamps(transcript, lag.Plan("vanilla", 0, "burst", 1), (10, 1000))
    assert (stamps.before, stamps.after) == (1, 0)
    assert stamps.around == {"+0/+3": 1}


def test_a_set_time_before_an_answer_with_its_game_time_was_stamped_after_the_tick(
    lag: types.ModuleType,
) -> None:
    transcript = _transcript(
        ("control", _answer(98)),
        ("control", _set_time(100)),
        ("control", _answer(100)),
    )
    stamps = lag.stamps(transcript, lag.Plan("pumpkin", 0, "burst", 1), (10, 1000))
    assert (stamps.before, stamps.after) == (0, 1)
    assert stamps.around == {"-2/+0": 1}


def test_only_controls_packets_inside_the_step_count(lag: types.ModuleType) -> None:
    transcript = _transcript(
        ("control", _answer(5)),
        ("control", _set_time(5)),  # before the step
        ("lag", _set_time(100)),  # another Bot's connection: its order is not Control's
        ("control", _answer(100)),
        ("control", _set_time(1000)),  # once the step has ended
    )
    stamps = lag.stamps(transcript, lag.Plan("vanilla", 0, "burst", 1), (10, 1000))
    assert (stamps.set_times, stamps.answers, stamps.before, stamps.after) == (0, 1, 0, 0)
