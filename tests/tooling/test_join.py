"""Hermetic tests for scripts/research/join.py: args, reporting, and JSONL, all without Java."""

import importlib.util
import json
import types
import uuid
from pathlib import Path

import pytest

from mscts.codec.packets import Direction, Packet, State
from mscts.transcript import Transcript
from tests.tooling.test_chunkformat import _payload, _section, _single

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "research" / "join.py"


@pytest.fixture
def join(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> types.ModuleType:
    # cache_dir() is read once at import time by ADAPTERS-independent code; give join.py
    # (and the boot.py it loads) an empty, throwaway cache so nothing on the real machine
    # can be touched by an accidental non-hermetic path.
    monkeypatch.setenv("MSCTS_CACHE", str(tmp_path / "cache"))
    spec = importlib.util.spec_from_file_location("research_join", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _packet(name: str, fields: dict[str, object] | None, *, payload: bytes = b"") -> Packet:
    return Packet(
        state=State.PLAY,
        direction=Direction.CLIENTBOUND,
        name=name,
        packet_id=0,
        payload=payload,
        fields=fields,
    )


def test_loads_boot_and_chunkformat_as_siblings(join: types.ModuleType) -> None:
    assert hasattr(join.boot, "spec_from_overrides")
    assert hasattr(join.chunkformat, "decode_chunk")


def test_parses_the_adapter_and_defaults(join: types.ModuleType) -> None:
    args = join.parse_args(["vanilla"])
    assert args.adapter == "vanilla"
    assert (args.spec, args.packets, args.chunks, args.out) == ([], "", 0, None)


def test_parses_spec_packets_chunks_and_out(join: types.ModuleType) -> None:
    args = join.parse_args(
        [
            "pumpkin",
            "--spec",
            "seed=1",
            "--packets",
            "minecraft:login,minecraft:player_position",
            "--chunks",
            "2",
            "--out",
            "t.jsonl",
        ]
    )
    assert args.spec == ["seed=1"]
    assert args.packets == "minecraft:login,minecraft:player_position"
    assert args.chunks == 2
    assert args.out == Path("t.jsonl")


def test_rejects_an_unknown_adapter(join: types.ModuleType) -> None:
    with pytest.raises(SystemExit) as error:
        join.parse_args(["not-an-adapter"])
    assert error.value.code == 2


def test_packet_names_splits_and_drops_empties(join: types.ModuleType) -> None:
    assert join.packet_names("") == frozenset()
    assert join.packet_names("minecraft:login,minecraft:hello") == frozenset(
        {"minecraft:login", "minecraft:hello"}
    )


def test_report_prints_only_the_named_packets_decoded_or_as_hex(
    join: types.ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    transcript = Transcript(scenario_id="t", server="vanilla")
    transcript.record("bot", _packet("minecraft:login", {"is_flat": False}), t_ns=0)
    transcript.record("bot", _packet("minecraft:hello", None, payload=b"\x01\x02"), t_ns=0)
    transcript.record("bot", _packet("minecraft:ignored", {"x": 1}), t_ns=0)

    join.report(transcript, frozenset({"minecraft:login", "minecraft:hello"}), 0)

    out = capsys.readouterr().out
    assert "minecraft:login {'is_flat': False}" in out
    assert "minecraft:hello 0102" in out
    assert "minecraft:ignored" not in out


def test_report_decodes_the_first_n_chunks(
    join: types.ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    section = _section(_single(5), _single(41), block_count=1)
    payload = _payload(1, 2, [section] * join.chunkformat.OVERWORLD_SECTIONS)
    transcript = Transcript(scenario_id="t", server="vanilla")
    transcript.record(
        "bot", _packet("minecraft:level_chunk_with_light", None, payload=payload), t_ns=0
    )
    transcript.record(
        "bot", _packet("minecraft:level_chunk_with_light", None, payload=payload), t_ns=0
    )

    join.report(transcript, frozenset(), 1)

    out = capsys.readouterr().out
    assert out.count("chunk (1, 2)") == 1  # only the first of the two, as asked


def test_jsonable_converts_bytes_and_uuid_recursively(join: types.ModuleType) -> None:
    value = uuid.UUID(int=1)
    converted = join.jsonable({"id": value, "raw": b"\x01\x02", "list": [b"\xff", value]})
    assert converted == {
        "id": str(value),
        "raw": "0102",
        "list": ["ff", str(value)],
    }
    json.dumps(converted)  # must not raise


def test_write_jsonl_writes_one_object_per_event(join: types.ModuleType, tmp_path: Path) -> None:
    transcript = Transcript(scenario_id="t", server="vanilla")
    transcript.record("bot", _packet("minecraft:login", {"is_flat": False}), t_ns=0)
    transcript.record("bot", _packet("minecraft:hello", None, payload=b"\x01\x02"), t_ns=0)
    out = tmp_path / "t.jsonl"

    join.write_jsonl(transcript, out)

    lines = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(lines) == 2
    assert lines[0]["name"] == "minecraft:login"
    assert lines[0]["fields"] == {"is_flat": False}
    assert lines[1]["name"] == "minecraft:hello"
    assert lines[1]["fields"] is None
    assert lines[1]["payload_hex"] == "0102"
