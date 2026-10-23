"""Hermetic tests for scripts/research/windows.py: a play's Observation windows as text."""

import importlib.util
import types
from pathlib import Path

import pytest

from mscts.codec.packets import Packet
from mscts.compare import OBSERVE_CLOSE, OBSERVE_NO_PLAY, OBSERVE_OPEN, TICK_MARK
from tests.compare.build import SERVERBOUND, packet, transcript

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "research" / "windows.py"
BLOCK, CHAT, COMMAND = "minecraft:block_update", "minecraft:system_chat", "minecraft:client_command"


@pytest.fixture
def windows() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("research_windows", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _chat(text: str = "hi") -> Packet:
    return packet(CHAT, fields={"message": text})


def test_a_window_lists_its_packets_and_says_which_it_compares(
    windows: types.ModuleType,
) -> None:
    played = transcript(
        ("alice", _chat()),  # before the window
        f"{OBSERVE_OPEN} {BLOCK}",
        ("alice", packet(COMMAND, direction=SERVERBOUND, fields={"command": "setblock"})),
        ("alice", packet(BLOCK, fields={"pos": (1, 2, 3)})),
        ("alice", _chat()),
        OBSERVE_CLOSE,
        ("alice", packet(BLOCK, fields={"pos": (4, 5, 6)})),  # after it
        group_id="probe/block",
    )

    assert windows.windows_text(played).splitlines() == [
        "probe/block on vanilla",
        f"window 1 (narrowed to {BLOCK})",
        f"      1.0 ms  alice  sent          {COMMAND}  " + "{'command': 'setblock'}",
        f"      2.0 ms  alice  compared      {BLOCK}  " + "{'pos': (1, 2, 3)}",
        f"      3.0 ms  alice  not compared  {CHAT}  " + "{'message': 'hi'}",
    ]


def test_each_window_is_listed_and_a_bot_s_packets_stop_at_its_own_close(
    windows: types.ModuleType,
) -> None:
    played = transcript(
        f"{OBSERVE_OPEN} {BLOCK}",
        ("alice", packet(BLOCK, fields={})),
        f"{OBSERVE_CLOSE} bob",
        ("bob", packet(BLOCK, fields={})),  # after bob's close, before the unnamed one
        ("alice", packet(BLOCK, fields={})),
        OBSERVE_CLOSE,
        f"{OBSERVE_OPEN}",
        ("bob", _chat("again")),
        f"{OBSERVE_OPEN} {OBSERVE_NO_PLAY}",
        ("bob", packet("minecraft:login", fields={"entity": 1})),
    )

    lines = windows.windows_text(played).splitlines()

    assert lines[1:] == [
        f"window 1 (narrowed to {BLOCK})",
        f"      1.0 ms  alice  compared      {BLOCK}  " + "{}",
        f"      4.0 ms  alice  compared      {BLOCK}  " + "{}",
        "window 2 (every packet)",
        f"      1.0 ms  bob    compared      {CHAT}  " + "{'message': 'again'}",
        "window 3 (compares no play packet)",
        "      1.0 ms  bob    not compared  minecraft:login  {'entity': 1}",
    ]


def test_a_tick_exact_play_gives_each_packet_its_tick(windows: types.ModuleType) -> None:
    played = transcript(
        f"{OBSERVE_OPEN} {BLOCK}",
        ("alice", packet(BLOCK, fields={})),
        f"{TICK_MARK}1",
        ("alice", packet(BLOCK, fields={})),
        OBSERVE_CLOSE,
    )

    assert windows.windows_text(played).splitlines()[2:] == [
        f"      1.0 ms  tick   1  alice  compared      {BLOCK}  " + "{}",
        f"      3.0 ms  tick   2  alice  compared      {BLOCK}  " + "{}",
    ]


def test_fields_are_cut_to_the_width_and_a_packet_with_no_schema_shows_its_payload(
    windows: types.ModuleType,
) -> None:
    played = transcript(
        OBSERVE_OPEN,
        ("alice", _chat("abcdefghij")),
        ("alice", packet("minecraft:unknown", b"\x01\x02")),
    )

    assert windows.windows_text(played, width=10).splitlines()[2:] == [
        f"      1.0 ms  alice  compared      {CHAT}  " + "{'message…",
        "      2.0 ms  alice  compared      minecraft:unknown  payload 0…",
    ]
    assert "{'message': 'abcdefghij'}" in windows.windows_text(played, width=None)


def test_a_play_with_no_window_says_so(windows: types.ModuleType) -> None:
    played = transcript(("alice", _chat()), group_id="status/basic")

    assert windows.windows_text(played).splitlines() == [
        "status/basic on vanilla",
        "no Observation window",
    ]
