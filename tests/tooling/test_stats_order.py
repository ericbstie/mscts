"""Hermetic tests for scripts/research/stats_order.py: reading each round's order (#376)."""

import importlib.util
import time
import types
from pathlib import Path

import pytest

from mscts.codec.packets import Direction, Packet, State
from mscts.spec import CONTROL_PLAYER
from mscts.transcript import Transcript

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "research" / "stats_order.py"


@pytest.fixture
def order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> types.ModuleType:
    monkeypatch.setenv("MSCTS_CACHE", str(tmp_path / "cache"))
    spec = importlib.util.spec_from_file_location("research_stats_order", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _packet(name: str, direction: Direction, **fields: object) -> Packet:
    return Packet(
        state=State.PLAY,
        direction=direction,
        name=name,
        packet_id=0,
        payload=b"",
        fields=fields,
    )


def _cell(cell: tuple[int, int, int]) -> dict[str, int]:
    x, y, z = cell
    return {"x": x, "y": y, "z": z}


def _place(order: types.ModuleType) -> Packet:
    return _packet("minecraft:use_item_on", Direction.SERVERBOUND, pos=_cell(order.TARGET_CELL))


def _request() -> Packet:
    return _packet("minecraft:client_command", Direction.SERVERBOUND, action=1)


def _answer() -> Packet:
    return _packet("minecraft:award_stats", Direction.CLIENTBOUND)


def _effect(cell: tuple[int, int, int], state: int = 1) -> Packet:
    return _packet(
        "minecraft:block_update", Direction.CLIENTBOUND, pos=_cell(cell), block_state=state
    )


def _step() -> Packet:
    return _packet("minecraft:chat_command", Direction.SERVERBOUND, command="tick step 1")


def _transcript(*received: tuple[str, Packet]) -> Transcript:
    transcript = Transcript(group_id="order", server="a", start_ns=time.monotonic_ns())
    for at, (bot, packet) in enumerate(received):
        transcript.record(bot, packet, t_ns=at * 1000)
    return transcript


def _round(order: types.ModuleType, *between: tuple[str, Packet]) -> list[tuple[str, Packet]]:
    """A place, then `between`, then Control's step."""
    return [(order.DIGGER, _place(order)), *between, (CONTROL_PLAYER, _step())]


def test_an_effect_before_the_last_answer_is_in_order(order: types.ModuleType) -> None:
    transcript = _transcript(
        *_round(
            order,
            (order.DIGGER, _request()),
            (order.DIGGER, _request()),
            (order.DIGGER, _effect(order.PLACED_CELL)),
            (order.DIGGER, _answer()),
            (order.DIGGER, _answer()),
        )
    )
    (only,) = order.rounds(transcript)
    assert only.in_order
    assert len(only.answers_ns) == 2


def test_an_effect_after_the_last_answer_is_out_of_order(order: types.ModuleType) -> None:
    transcript = _transcript(
        *_round(
            order,
            (order.DIGGER, _request()),
            (order.DIGGER, _request()),
            (order.DIGGER, _answer()),
            (order.DIGGER, _answer()),
        ),
        (order.DIGGER, _effect(order.PLACED_CELL)),
    )
    (only,) = order.rounds(transcript)
    assert not only.in_order


def test_no_effect_is_out_of_order(order: types.ModuleType) -> None:
    transcript = _transcript(
        *_round(order, (order.DIGGER, _request()), (order.DIGGER, _answer())),
    )
    (only,) = order.rounds(transcript)
    assert only.effect_ns is None
    assert not only.in_order


def test_the_effect_is_the_placed_cell_turning_to_a_block(order: types.ModuleType) -> None:
    transcript = _transcript(
        *_round(
            order,
            (order.DIGGER, _effect(order.TARGET_CELL)),
            (order.DIGGER, _effect(order.PLACED_CELL, state=0)),
            (order.DIGGER, _answer()),
        ),
        (order.DIGGER, _effect(order.PLACED_CELL)),
    )
    (only,) = order.rounds(transcript)
    assert only.effect_ns == 5000
    assert not only.in_order


def test_each_round_takes_only_its_own_answers_and_effect(order: types.ModuleType) -> None:
    transcript = _transcript(
        *_round(order, (order.DIGGER, _answer()), (order.DIGGER, _answer())),
        (order.DIGGER, _answer()),
        *_round(
            order,
            (order.DIGGER, _effect(order.PLACED_CELL)),
            (order.DIGGER, _answer()),
            (order.DIGGER, _answer()),
        ),
    )
    first, second = order.rounds(transcript)
    assert first.effect_ns is None
    assert len(first.answers_ns) == 2
    assert second.in_order
    assert second.answers_ns == (2000, 3000)
