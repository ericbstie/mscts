"""Hermetic tests for scripts/research/probe_window_edges.py: what crosses a window's edges."""

import importlib.util
import time
import types
from pathlib import Path

import pytest

from mscts.codec.packets import Direction
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN
from mscts.transcript import Mark, Transcript
from tests.compare.build import packet

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "research" / "probe_window_edges.py"
_MS = 1_000_000
BLOCK, CHAT = "minecraft:block_update", "minecraft:system_chat"


@pytest.fixture
def edges() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("research_probe_window_edges", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _play() -> Transcript:
    """Setup, a window narrowed to block updates around the builder's command, then setup."""
    transcript = Transcript(group_id="probe", server="a", start_ns=time.monotonic_ns() - 10**9)
    command = packet("minecraft:chat_command", direction=Direction.SERVERBOUND)

    def at(ms: int, bot: str, name: str, *, sent: bool = False) -> None:
        received = command if sent else packet(name)
        transcript.record(bot, received, t_ns=ms * _MS)

    at(1, "control", "", sent=True)
    at(10, "builder", BLOCK)  # setup's change, before the window
    transcript.marks.append(Mark(t_ns=40 * _MS, label=f"{OBSERVE_OPEN} {BLOCK}"))
    at(45, "builder", BLOCK)  # setup's change that crossed into the window
    at(50, "builder", "", sent=True)
    at(60, "builder", BLOCK)  # the command's own
    at(61, "builder", CHAT)  # not one the window compares
    transcript.marks.append(Mark(t_ns=100 * _MS, label=f"{OBSERVE_CLOSE} builder"))
    transcript.marks.append(Mark(t_ns=120 * _MS, label=OBSERVE_CLOSE))
    at(110, "builder", BLOCK)  # the command's, after the builder's own close
    at(130, "control", "", sent=True)
    at(140, "builder", BLOCK)  # the next setup's
    return transcript


def test_a_window_reports_what_crossed_its_edges(edges: types.ModuleType) -> None:
    (window,) = edges.windows(_play(), "builder")

    assert window == {
        "margin_ms": 30.0,
        "leaked": [["block_update", 5.0]],
        "late": [["block_update", 10.0]],
    }


def test_another_bot_sees_no_packets_of_the_builder(edges: types.ModuleType) -> None:
    (window,) = edges.windows(_play(), "control")

    assert window == {"margin_ms": None, "leaked": [], "late": []}
