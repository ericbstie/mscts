"""Hermetic tests for scripts/research/probe_loop.py: summaries, saved plays, the loop."""

import contextlib
import importlib.util
import json
import struct
import time
import types
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from mscts.codec.packets import Direction, Packet, State
from mscts.group import Group, GroupContext
from mscts.net import Endpoint
from mscts.run import GroupError
from mscts.spec import ServerSpec
from mscts.transcript import Mark, Transcript

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "research" / "probe_loop.py"
_MS = 1_000_000
_ENDPOINTS = [Endpoint(host="127.0.0.1", port=1), Endpoint(host="127.0.0.1", port=2)]


@pytest.fixture
def probe_loop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> types.ModuleType:
    # The script loads boot.py and join.py, which read the cache location at import.
    monkeypatch.setenv("MSCTS_CACHE", str(tmp_path / "cache"))
    spec = importlib.util.spec_from_file_location("research_probe_loop", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _blank() -> Transcript:
    """A Transcript that started a second ago, so that events can be recorded at fixed times."""
    return Transcript(group_id="probe", server="a", start_ns=time.monotonic_ns() - 1_000_000_000)


def _packet(
    name: str, *, payload: bytes = b"", direction: Direction = Direction.CLIENTBOUND
) -> Packet:
    return Packet(
        state=State.PLAY, direction=direction, name=name, packet_id=0, payload=payload, fields=None
    )


def _chunk(x: int, z: int) -> Packet:
    return _packet("minecraft:level_chunk_with_light", payload=struct.pack(">ii", x, z) + b"\0")


def _transcript(*, watcher_update: bool, control_update_ms: int) -> Transcript:
    """A play: the watcher joins (9 chunks, (0, 0) among them); a window; the barrier's answers."""
    transcript = _blank()
    record = transcript.record
    for x, z in [(1, 1), (0, 0), (-1, 0)]:
        record("watcher", _chunk(x, z), t_ns=10 * _MS)
    record("watcher", _packet("minecraft:chunk_batch_finished"), t_ns=10 * _MS)
    # Before the window, Control's earlier barrier and an earlier block change.
    record("control", _packet("minecraft:award_stats"), t_ns=50 * _MS)
    record("control", _packet("minecraft:block_update"), t_ns=20 * _MS)
    transcript.marks.append(Mark(t_ns=100 * _MS, label="observe:open minecraft:block_update"))
    answer = _packet("minecraft:award_stats")
    for t_ms in (110, 160):
        record("control", answer, t_ns=t_ms * _MS)
    for t_ms in (111, 161):
        record("watcher", answer, t_ns=t_ms * _MS)
    transcript.marks.append(Mark(t_ns=170 * _MS, label="observe:close"))
    record("control", answer, t_ns=180 * _MS)  # a later barrier, outside the window
    record("control", _packet("minecraft:block_update"), t_ns=control_update_ms * _MS)
    if watcher_update:
        record("watcher", _packet("minecraft:block_update"), t_ns=165 * _MS)
    return transcript


def test_chunk_xz_reads_the_two_signed_ints_a_chunk_payload_starts_with(
    probe_loop: types.ModuleType,
) -> None:
    assert probe_loop.chunk_xz(struct.pack(">ii", -3, 7) + b"rest") == (-3, 7)


def test_summarise_says_when_the_watchers_chunks_came_and_how_the_window_ended(
    probe_loop: types.ModuleType,
) -> None:
    side = probe_loop.summarise(_transcript(watcher_update=True, control_update_ms=165))

    assert (side.first_batch_ms, side.chunk00_ms, side.chunks) == (10.0, 10.0, 3)
    assert (side.open_ms, side.close_ms) == (100.0, 170.0)
    assert side.gaps_ms == {"control": [50.0], "watcher": [50.0]}
    assert side.update_ms == {"control": 165.0, "watcher": 165.0}
    assert (side.update_where("control"), side.update_where("watcher")) == ("in", "in")


def test_a_block_update_after_the_close_or_never_is_told_apart_from_one_inside(
    probe_loop: types.ModuleType,
) -> None:
    side = probe_loop.summarise(_transcript(watcher_update=False, control_update_ms=175))

    assert side.update_where("control") == "AFTER_CLOSE"
    assert side.update_where("watcher") == "none"
    assert "control_update=AFTER_CLOSE(175.0)" in side.line()
    assert "watcher_update=none(None)" in side.line()


def test_summarise_times_each_bots_sync_and_names_the_bots_whose_sync_was_capped(
    probe_loop: types.ModuleType,
) -> None:
    transcript = _blank()
    record = transcript.record
    request = _packet("minecraft:client_command", direction=Direction.SERVERBOUND)
    answer = _packet("minecraft:award_stats")
    record("control", request, t_ns=90 * _MS)  # a request before the window is not its sync
    transcript.marks.append(Mark(t_ns=100 * _MS, label="observe:open"))
    for t_ms, packet in [(101, request), (102, answer), (102, request), (152, answer)]:
        record("control", packet, t_ns=t_ms * _MS)
    for t_ms, packet in [(103, request), (104, answer), (104, request), (105, answer)]:
        record("watcher", packet, t_ns=t_ms * _MS)
    transcript.marks.append(Mark(t_ns=160 * _MS, label="sync:capped watcher"))
    transcript.marks.append(Mark(t_ns=170 * _MS, label="observe:close"))

    side = probe_loop.summarise(transcript)

    assert side.sync_ms == {"control": 51.0, "watcher": 2.0}
    assert side.capped == ("watcher",)
    assert "control_sync=51.0" in side.line()
    assert "capped=watcher" in side.line()


def test_a_side_with_no_capped_sync_says_so_and_a_bot_that_never_synced_has_no_time(
    probe_loop: types.ModuleType,
) -> None:
    side = probe_loop.summarise(_transcript(watcher_update=True, control_update_ms=165))

    assert side.capped == ()
    assert side.sync_ms == {"control": None, "watcher": None}
    assert "capped=none" in side.line()
    assert "control_sync=None" in side.line()


def test_a_window_that_never_opened_has_no_gaps_and_no_updates(
    probe_loop: types.ModuleType,
) -> None:
    transcript = _blank()
    transcript.record("control", _packet("minecraft:award_stats"), t_ns=5 * _MS)
    transcript.record("control", _packet("minecraft:block_update"), t_ns=6 * _MS)

    side = probe_loop.summarise(transcript)

    assert (side.open_ms, side.close_ms, side.chunks, side.chunk00_ms) == (None, None, 0, None)
    assert side.gaps_ms == {"control": [], "watcher": []}
    assert side.update_ms == {"control": None, "watcher": None}


def test_save_writes_the_marks_then_each_event_as_one_json_object(
    probe_loop: types.ModuleType, tmp_path: Path
) -> None:
    transcript = _transcript(watcher_update=True, control_update_ms=165)
    out = tmp_path / "play.jsonl"

    probe_loop.save(transcript, out)

    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert [row["mark"] for row in rows[:2]] == [
        "observe:open minecraft:block_update",
        "observe:close",
    ]
    events = rows[2:]
    assert len(events) == len(transcript.events)
    chunk = next(row for row in events if row["chunk"] == [0, 0])
    assert chunk["name"] == "minecraft:level_chunk_with_light"
    assert chunk["payload_hex"] == struct.pack(">ii", 0, 0).hex() + "00"
    assert all(row["chunk"] is None for row in events if row["name"] != chunk["name"])


@pytest.mark.parametrize("size", [63, 64, 2048])
def test_save_keeps_every_byte_of_a_long_payload(
    probe_loop: types.ModuleType, tmp_path: Path, size: int
) -> None:
    transcript = _blank()
    payload = bytes(index % 256 for index in range(size))
    transcript.record("watcher", _packet("minecraft:set_time", payload=payload), t_ns=0)
    out = tmp_path / "play.jsonl"

    probe_loop.save(transcript, out)

    (row,) = [json.loads(line) for line in out.read_text().splitlines()]
    assert bytes.fromhex(row["payload_hex"]) == payload


async def _nothing(context: GroupContext) -> None:
    del context


_GROUP = Group(id="probe/test", run=_nothing)


def _plays(transcripts: list[Transcript | GroupError]) -> object:
    """A `play` that gives each call the next of `transcripts`, as the loop's two sides do."""
    remaining = list(transcripts)

    async def play(group: Group, endpoint: Endpoint, *, server: str) -> Transcript:  # noqa: ARG001 - run_group's shape
        outcome = remaining.pop(0)
        if isinstance(outcome, GroupError):
            raise outcome
        return outcome

    return play


@pytest.mark.asyncio
async def test_a_loop_of_matching_plays_saves_nothing(
    probe_loop: types.ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    transcripts: list[Transcript | GroupError] = [
        _transcript(watcher_update=True, control_update_ms=165) for _ in range(4)
    ]

    not_matching = await probe_loop.loop(
        _GROUP, _ENDPOINTS, 2, tmp_path / "out", play=_plays(transcripts)
    )

    out = capsys.readouterr().out
    assert not_matching == 0
    assert [line.split()[:3] for line in out.splitlines()[:2]] == [
        ["0", "ok", "match"],
        ["1", "ok", "match"],
    ]
    assert not (tmp_path / "out").exists()


@pytest.mark.asyncio
async def test_a_play_that_does_not_match_has_both_transcripts_saved(
    probe_loop: types.ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = _transcript(watcher_update=True, control_update_ms=165)
    bad = _transcript(watcher_update=False, control_update_ms=175)
    transcripts: list[Transcript | GroupError] = [good, good, good, bad]

    not_matching = await probe_loop.loop(
        _GROUP, _ENDPOINTS, 2, tmp_path / "out", play=_plays(transcripts)
    )

    out = capsys.readouterr().out
    assert not_matching == 1
    lines = [line.split()[:3] for line in out.splitlines() if line[:1].isdigit()]
    assert lines == [["0", "ok", "match"], ["1", "BAD", "mismatch"]]
    assert "watcher_update=none(None)" in out
    assert sorted(path.name for path in (tmp_path / "out").iterdir()) == [
        "play-1-a.jsonl",
        "play-1-b.jsonl",
    ]


@pytest.mark.asyncio
async def test_a_side_whose_group_raised_is_judged_and_its_transcript_saved(
    probe_loop: types.ModuleType, tmp_path: Path
) -> None:
    good = _transcript(watcher_update=True, control_update_ms=165)
    partial = _blank()
    partial.record("watcher", _packet("minecraft:set_time"), t_ns=5 * _MS)
    failed = GroupError(partial, "boom")

    not_matching = await probe_loop.loop(
        _GROUP, _ENDPOINTS, 1, tmp_path / "out", play=_plays([good, failed])
    )

    assert not_matching == 1
    saved = (tmp_path / "out" / "play-0-b.jsonl").read_text()
    assert [json.loads(line)["name"] for line in saved.splitlines()] == ["minecraft:set_time"]


def test_parses_the_plays_the_directory_and_the_stress(probe_loop: types.ModuleType) -> None:
    args = probe_loop.parse_args(["300", "out"])
    assert (args.plays, args.out_dir, args.stress) == (300, Path("out"), 0)
    assert probe_loop.parse_args(["5", "out", "--stress", "4"]).stress == 4


def test_rejects_a_count_that_is_not_a_number(probe_loop: types.ModuleType) -> None:
    with pytest.raises(SystemExit) as error:
        probe_loop.parse_args(["many", "out"])
    assert error.value.code == 2


@pytest.mark.asyncio
async def test_run_uses_the_supplied_loop_with_both_prepared_endpoints(
    probe_loop: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared: list[Endpoint] = []

    def prepare(_installation: object, spec: ServerSpec, _cwd: Path) -> types.SimpleNamespace:
        endpoint = Endpoint(spec.host, spec.port)
        prepared.append(endpoint)
        return types.SimpleNamespace(endpoint=endpoint)

    @contextlib.asynccontextmanager
    async def fake_running(plan: object, **_kwargs: object) -> AsyncIterator[object]:
        yield plan

    async def custom(group: Group, endpoints: list[Endpoint], plays: int, out: Path) -> int:
        assert group is _GROUP
        assert endpoints == prepared
        assert len(endpoints) == 2
        assert plays == 3
        assert out == tmp_path / "out"
        return 2

    monkeypatch.setattr(
        probe_loop, "VanillaAdapter", lambda: types.SimpleNamespace(prepare=prepare)
    )
    monkeypatch.setattr(probe_loop.install, "require", lambda *_args: None)
    monkeypatch.setattr(probe_loop, "running", fake_running)

    assert await probe_loop.run(_GROUP, 3, tmp_path / "out", tmp_path, loop=custom) == 2


@pytest.mark.asyncio
async def test_loop_prints_totals_and_tallies_divergences_by_test_case(
    probe_loop: types.ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = _transcript(watcher_update=True, control_update_ms=165)
    bad = _transcript(watcher_update=False, control_update_ms=175)
    await probe_loop.loop(
        _GROUP, _ENDPOINTS, 3, tmp_path / "out", play=_plays([good, bad, good, bad, good, good])
    )
    out = capsys.readouterr().out
    assert "totals: 3 plays, 1 matched" in out, out
    assert "  block_update: 2 Divergences" in out, out


def test_a_finished_probe_with_mismatches_exits_zero(
    probe_loop: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def finished(*_args: object) -> int:
        return 1

    monkeypatch.setattr(probe_loop, "run", finished)
    assert probe_loop.main(["1", str(tmp_path / "out")]) == 0


def test_a_crashed_probe_raises_and_removes_its_workdir(
    probe_loop: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workdirs: list[Path] = []

    async def crash(_group: Group, _plays: int, _out: Path, workdir: Path) -> int:
        workdirs.append(workdir)
        (workdir / "started").touch()
        msg = "deliberate probe crash"
        raise RuntimeError(msg)

    monkeypatch.setattr(probe_loop, "run", crash)
    with pytest.raises(RuntimeError, match="deliberate probe crash"):
        probe_loop.main(["1", str(tmp_path / "out")])
    assert len(workdirs) == 1
    assert not workdirs[0].exists()
