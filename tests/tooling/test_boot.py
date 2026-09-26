"""Hermetic tests for scripts/research/boot.py: argument parsing, --spec, and a real run."""

import importlib.util
import types
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from support.leak_guard import kill_survivors

from mscts.adapters.base import Installation
from mscts.net import Endpoint
from mscts.runner import free_endpoint
from mscts.spec import Difficulty, GameMode, ServerSpec, WorldPreset
from mscts.target import TARGET
from tests.run.fakes import TOKEN_VAR, FakeAdapter

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "research" / "boot.py"
_ENDPOINT = Endpoint(host="127.0.0.1", port=25565)


@pytest.fixture
def boot() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("research_boot", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parses_the_adapter_workdir_and_defaults(boot: types.ModuleType, tmp_path: Path) -> None:
    args = boot.parse_args(["vanilla", str(tmp_path)])
    assert (args.adapter, args.workdir) == ("vanilla", tmp_path)
    assert (args.spec, args.keep, args.seconds) == ([], False, None)


def test_parses_repeated_spec_keep_and_seconds(boot: types.ModuleType, tmp_path: Path) -> None:
    args = boot.parse_args(
        [
            "pumpkin",
            str(tmp_path),
            "--spec",
            "seed=1",
            "--spec",
            "motd=hi",
            "--keep",
            "--seconds",
            "2.5",
        ]
    )
    assert args.spec == ["seed=1", "motd=hi"]
    assert (args.keep, args.seconds) == (True, 2.5)


def test_rejects_an_unknown_adapter(boot: types.ModuleType, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as error:
        boot.parse_args(["not-an-adapter", str(tmp_path)])
    assert error.value.code == 2


def test_spec_from_overrides_defaults_to_the_endpoint_and_serverspec_defaults(
    boot: types.ModuleType,
) -> None:
    spec = boot.spec_from_overrides([], _ENDPOINT)
    assert spec == ServerSpec(host=_ENDPOINT.host, port=_ENDPOINT.port)


def test_spec_from_overrides_converts_each_field_type(boot: types.ModuleType) -> None:
    spec = boot.spec_from_overrides(
        [
            "motd=research",
            "max_players=5",
            "seed=42",
            "world=flat",
            "game_mode=creative",
            "difficulty=hard",
            "operators=alice,bob",
        ],
        _ENDPOINT,
    )
    assert spec.motd == "research"
    assert spec.max_players == 5
    assert spec.seed == 42
    assert spec.world is WorldPreset.FLAT
    assert spec.game_mode is GameMode.CREATIVE
    assert spec.difficulty is Difficulty.HARD
    assert spec.operators == ("alice", "bob")


def test_spec_from_overrides_rejects_a_pair_with_no_equals(boot: types.ModuleType) -> None:
    with pytest.raises(ValueError, match="is not key=value"):
        boot.spec_from_overrides(["seed"], _ENDPOINT)


def test_spec_from_overrides_rejects_host_and_port(boot: types.ModuleType) -> None:
    with pytest.raises(ValueError, match="comes from the Endpoint"):
        boot.spec_from_overrides(["host=127.0.0.2"], _ENDPOINT)
    with pytest.raises(ValueError, match="comes from the Endpoint"):
        boot.spec_from_overrides(["port=1"], _ENDPOINT)


def test_spec_from_overrides_rejects_an_unknown_field(boot: types.ModuleType) -> None:
    with pytest.raises(ValueError, match="not a ServerSpec field"):
        boot.spec_from_overrides(["nonesuch=1"], _ENDPOINT)


def test_spec_from_overrides_rejects_a_value_of_the_wrong_type(boot: types.ModuleType) -> None:
    with pytest.raises(ValueError, match=r"seed=.*not-a-number"):
        boot.spec_from_overrides(["seed=not-a-number"], _ENDPOINT)


def test_spec_from_overrides_rejects_an_unknown_enum_value(boot: types.ModuleType) -> None:
    with pytest.raises(ValueError, match=r"difficulty=.*extreme"):
        boot.spec_from_overrides(["difficulty=extreme"], _ENDPOINT)


@pytest.fixture
def run_token() -> Iterator[str]:
    """A token for this test's fake Instances; fails the test if one outlives it."""
    token = uuid.uuid4().hex
    yield token
    leaked = kill_survivors(f"{TOKEN_VAR}={token}")
    assert not leaked, f"fake Instances outlived the test: {leaked}"


@pytest.fixture
def fake_adapter(run_token: str) -> Callable[..., FakeAdapter]:
    def make(name: str = "fake") -> FakeAdapter:
        return FakeAdapter(name=name, token=run_token)

    return make


@pytest.mark.asyncio
async def test_boot_runs_seconds_then_stops_and_removes_the_workdir(
    boot: types.ModuleType,
    fake_adapter: Callable[..., FakeAdapter],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    adapter = fake_adapter()
    installation = Installation(adapter=adapter.name, target=TARGET, root=tmp_path / "install")
    endpoint = free_endpoint()
    spec = ServerSpec(host=endpoint.host, port=endpoint.port, motd="research run")
    workdir = tmp_path / "workdir"
    prepared = boot.Prepared(adapter, installation, spec, workdir)

    await boot.boot(prepared, seconds=0.05, keep=False)

    assert not workdir.exists()
    assert f"{endpoint.host}:{endpoint.port} ready in" in capsys.readouterr().out
    assert adapter.prepared == [spec]


@pytest.mark.asyncio
async def test_boot_keep_leaves_the_workdir(
    boot: types.ModuleType,
    fake_adapter: Callable[..., FakeAdapter],
    tmp_path: Path,
) -> None:
    adapter = fake_adapter()
    installation = Installation(adapter=adapter.name, target=TARGET, root=tmp_path / "install")
    endpoint = free_endpoint()
    spec = ServerSpec(host=endpoint.host, port=endpoint.port)
    workdir = tmp_path / "workdir"
    prepared = boot.Prepared(adapter, installation, spec, workdir)

    await boot.boot(prepared, seconds=0.05, keep=True)

    assert workdir.is_dir()
