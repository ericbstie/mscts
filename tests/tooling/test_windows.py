"""Hermetic tests for scripts/research/windows.py: a play's Observation windows as text."""

import contextlib
import importlib.util
import types
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path

import pytest

from mscts import install
from mscts.codec.packets import Packet
from mscts.compare import OBSERVE_CLOSE, OBSERVE_NO_PLAY, OBSERVE_OPEN, TICK_MARK
from mscts.group import Group, GroupContext
from mscts.net import Endpoint
from mscts.run import GroupError
from mscts.spec import ServerSpec
from mscts.transcript import Transcript
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


async def _nothing(context: GroupContext) -> None:
    """A Group script that does nothing."""


def _group() -> Group:
    return Group(
        id="probe/test", run=_nothing, spec=lambda spec: replace(spec, operators=("alice",))
    )


@pytest.mark.asyncio
async def test_play_boots_one_instance_with_the_groups_spec_and_plays_the_group_once(
    windows: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared: list[ServerSpec] = []
    played: list[tuple[Group, Endpoint, str]] = []
    result = transcript(("alice", _chat()))

    def prepare(_installation: object, spec: ServerSpec, _cwd: Path) -> types.SimpleNamespace:
        prepared.append(spec)
        return types.SimpleNamespace(endpoint=Endpoint(spec.host, spec.port))

    @contextlib.asynccontextmanager
    async def fake_running(plan: object, **_kwargs: object) -> AsyncIterator[object]:
        yield plan

    async def fake_run_group(group: Group, endpoint: Endpoint, *, server: str) -> Transcript:
        played.append((group, endpoint, server))
        return result

    monkeypatch.setattr(
        windows, "VanillaAdapter", lambda: types.SimpleNamespace(name="vanilla", prepare=prepare)
    )
    monkeypatch.setattr(windows.install, "require", lambda *_args: None)
    monkeypatch.setattr(windows, "running", fake_running)
    monkeypatch.setattr(windows, "run_group", fake_run_group)
    group = _group()

    assert await windows.play(group, tmp_path) is result

    assert [spec.operators for spec in prepared] == [("alice",)]
    assert played == [(group, Endpoint(prepared[0].host, prepared[0].port), "vanilla")]


def _playing(
    windows: types.ModuleType, monkeypatch: pytest.MonkeyPatch, outcome: Transcript | Exception
) -> list[Path]:
    """Make `windows.play` give `outcome` (raise it, if an error); the workdirs it is given."""
    workdirs: list[Path] = []

    async def play(group: Group, workdir: Path) -> Transcript:  # noqa: ARG001 - play's shape
        workdirs.append(workdir)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(windows, "play", play)
    return workdirs


def test_main_prints_the_windows_of_the_group_and_removes_its_workdir(
    windows: types.ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    played = transcript(f"{OBSERVE_OPEN} {BLOCK}", ("alice", packet(BLOCK, fields={})))
    workdirs = _playing(windows, monkeypatch, played)

    code = windows.main(["probe/test"], groups={"probe/test": _group()})

    assert code == 0
    assert capsys.readouterr().out == windows.windows_text(played) + "\n"
    assert [workdir.exists() for workdir in workdirs] == [False]


def test_main_cuts_the_fields_unless_asked_for_all_of_them(
    windows: types.ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    long = "x" * (windows.FIELDS_WIDTH + 50)
    _playing(windows, monkeypatch, transcript(OBSERVE_OPEN, ("alice", _chat(long))))
    groups = {"probe/test": _group()}

    windows.main(["probe/test"], groups=groups)
    cut = capsys.readouterr().out
    windows.main(["probe/test", "--full"], groups=groups)
    full = capsys.readouterr().out

    assert long not in cut
    assert cut.splitlines()[2].endswith("…")
    assert long in full


def test_main_names_a_group_that_is_not_registered(
    windows: types.ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workdirs = _playing(windows, monkeypatch, transcript())

    code = windows.main(["player/nothing"], groups={"probe/test": _group()})

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert captured.err == "windows.py: no Group is registered as 'player/nothing'\n"
    assert workdirs == []


def test_main_prints_the_windows_so_far_of_a_group_that_raised(
    windows: types.ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    partial = transcript(f"{OBSERVE_OPEN} {BLOCK}", ("alice", packet(BLOCK, fields={})))
    _playing(windows, monkeypatch, GroupError(partial, "bot alice timed out"))

    code = windows.main(["probe/test"], groups={"probe/test": _group()})

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == windows.windows_text(partial) + "\n"
    assert captured.err == "windows.py: probe/test failed: bot alice timed out\n"


def test_main_says_what_is_wrong_when_vanilla_is_not_installed(
    windows: types.ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workdirs = _playing(windows, monkeypatch, install.ProvisionError("no vanilla installed"))

    code = windows.main(["probe/test"], groups={"probe/test": _group()})

    captured = capsys.readouterr()
    assert code == 1
    assert captured.err == "windows.py: no vanilla installed\n"
    assert [workdir.exists() for workdir in workdirs] == [False]


def test_a_group_id_is_required(windows: types.ModuleType) -> None:
    with pytest.raises(SystemExit) as error:
        windows.parse_args([])
    assert error.value.code == 2
