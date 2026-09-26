import gzip
from pathlib import Path
from types import MappingProxyType

import pytest

from mscts.adapters import pumpkin
from mscts.adapters.base import Adapter, Installation, LaunchPlan, PrepareError
from mscts.adapters.pumpkin import Limit, PumpkinAdapter, ops_json, pumpkin_toml
from mscts.net import Endpoint
from mscts.spec import Difficulty, ServerSpec, WorldPreset
from mscts.target import TARGET

# Any host address of 127.0.0.0/8 will do: prepare only writes it into the config.
HOST = "127.1.2.3"
DATA = Path(__file__).parent / "data"


@pytest.fixture
def installation(tmp_path: Path) -> Installation:
    return Installation(adapter="pumpkin", target=TARGET, root=tmp_path / "cache/pumpkin/26.3")


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    return tmp_path / "work"


def nothing_in(workdir: Path) -> bool:
    return not workdir.exists() or not any(workdir.iterdir())


# What Pumpkin cannot honour (LIMITS). Every ServerSpec value today is honoured, so these
# tests narrow LIMITS to check that it is enforced.


def test_every_worldpreset_and_difficulty_is_honoured() -> None:
    assert set(pumpkin.LIMITS) == {"world"}
    assert pumpkin.LIMITS["world"].honoured == frozenset(WorldPreset)


def test_prepare_refuses_a_value_outside_its_limit_and_writes_nothing(
    installation: Installation, workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    limits = {"world": Limit(frozenset(), "no world"), "motd": Limit(frozenset(), "no motd")}
    monkeypatch.setattr(pumpkin, "LIMITS", MappingProxyType(limits))
    with pytest.raises(PrepareError) as refusal:
        PumpkinAdapter().prepare(installation, ServerSpec(host=HOST, port=25599), workdir)
    # Every field it cannot honour is named at once.
    assert "ServerSpec.world=flat: no world" in str(refusal.value)
    assert "ServerSpec.motd=mscts: no motd" in str(refusal.value)
    assert nothing_in(workdir)


def test_pumpkin_is_an_adapter(installation: Installation, workdir: Path) -> None:
    adapter: Adapter = PumpkinAdapter()
    assert adapter.name == "pumpkin"
    adapter.prepare(installation, ServerSpec(host=HOST, port=25599), workdir)


def _written(workdir: Path) -> dict[str, bytes]:
    """Every file in `workdir`, the world save's gunzipped."""
    return {
        path.relative_to(workdir).as_posix(): (
            gzip.decompress(path.read_bytes()) if path.suffix == ".dat" else path.read_bytes()
        )
        for path in workdir.rglob("*")
        if path.is_file()
    }


# The world save for the default ServerSpec (flat, seed 0, peaceful), uncompressed. Pumpkin's
# own new-world level.dat with the substitutions level_dat() documents, and the
# world_gen_settings.dat vanilla writes, in Pumpkin's layout. A Pumpkin booted on them read
# them back unchanged but for those (docs/research/2026-09-26-pumpkin.md).
GOLDEN_LEVEL = (DATA / "pumpkin-26.3-default-spec.level.nbt").read_bytes()
GOLDEN_WORLD_GEN = (DATA / "pumpkin-26.3-default-spec.world_gen_settings.nbt").read_bytes()


def test_prepare_writes_the_complete_config_and_world_save(
    installation: Installation, workdir: Path
) -> None:
    spec = ServerSpec(host=HOST, port=25599, operators=("Notch",))
    PumpkinAdapter().prepare(installation, spec, workdir)
    assert _written(workdir) == {
        "pumpkin.toml": pumpkin_toml(spec).encode(),
        "data/ops.json": ops_json(("Notch",)).encode(),
        # Pumpkin's own first-run content of each; no ServerSpec field changes them.
        "data/whitelist.json": b"[]",
        "data/banned-players.json": b"[]",
        "data/banned-ips.json": b"[]",
        "world/level.dat": GOLDEN_LEVEL,
        "world/data/minecraft/world_gen_settings.dat": GOLDEN_WORLD_GEN,
    }


def _nbt_string(text: str) -> bytes:
    return len(text).to_bytes(2) + text.encode()


def test_each_value_the_tests_substitute_is_in_the_golden_files_once() -> None:
    long_seed = b"\x04" + _nbt_string("seed") + bytes(8)
    assert GOLDEN_LEVEL.count(b"\x08" + _nbt_string("difficulty") + _nbt_string("peaceful")) == 1
    assert GOLDEN_LEVEL.count(b"\x01" + _nbt_string("Difficulty") + b"\x00") == 1
    assert (GOLDEN_LEVEL.count(long_seed), GOLDEN_WORLD_GEN.count(long_seed)) == (1, 1)


DIFFICULTY_IDS = {
    Difficulty.PEACEFUL: 0,
    Difficulty.EASY: 1,
    Difficulty.NORMAL: 2,
    Difficulty.HARD: 3,
}


@pytest.mark.parametrize("difficulty", list(Difficulty), ids=[str(d) for d in Difficulty])
def test_the_level_dat_carries_the_difficulty(
    installation: Installation, workdir: Path, difficulty: Difficulty
) -> None:
    spec = ServerSpec(host=HOST, port=25599, difficulty=difficulty)
    PumpkinAdapter().prepare(installation, spec, workdir)
    # difficulty_settings.difficulty (the one Pumpkin reads) and the Difficulty byte.
    named = b"\x08" + _nbt_string("difficulty")
    difficulty_byte = b"\x01" + _nbt_string("Difficulty")
    expected = GOLDEN_LEVEL.replace(
        named + _nbt_string("peaceful"), named + _nbt_string(str(difficulty))
    ).replace(difficulty_byte + b"\x00", difficulty_byte + bytes([DIFFICULTY_IDS[difficulty]]))
    written = _written(workdir)
    assert written["world/level.dat"] == expected
    assert written["world/data/minecraft/world_gen_settings.dat"] == GOLDEN_WORLD_GEN


@pytest.mark.parametrize("seed", [-(2**63), -1, 2**63 - 1])
def test_the_world_save_carries_the_seed(
    installation: Installation, workdir: Path, seed: int
) -> None:
    PumpkinAdapter().prepare(installation, ServerSpec(host=HOST, port=25599, seed=seed), workdir)
    long_seed = b"\x04" + _nbt_string("seed")
    zero, spec_seed = long_seed + bytes(8), long_seed + seed.to_bytes(8, signed=True)
    written = _written(workdir)
    assert written["world/level.dat"] == GOLDEN_LEVEL.replace(zero, spec_seed)
    assert written["world/data/minecraft/world_gen_settings.dat"] == GOLDEN_WORLD_GEN.replace(
        zero, spec_seed
    )


def test_prepare_returns_the_launch_plan(installation: Installation, workdir: Path) -> None:
    plan = PumpkinAdapter().prepare(installation, ServerSpec(host=HOST, port=25599), workdir)
    assert plan == LaunchPlan(
        argv=(str(installation.root / "pumpkin"),),  # it takes no arguments
        cwd=workdir,
        env={},
        endpoint=Endpoint(host=HOST, port=25599),  # exactly what it binds
        stop_stdin=b"stop\n",
    )


def test_nothing_from_the_harness_environment_reaches_pumpkin(
    installation: Installation, workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Pumpkin reads RUST_LOG (its log filter) and, through reqwest, the proxy variables.
    monkeypatch.setenv("RUST_LOG", "trace")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:3128")
    plan = PumpkinAdapter().prepare(installation, ServerSpec(host=HOST, port=25599), workdir)
    assert dict(plan.env) == {}


def test_the_binary_path_is_absolute_so_it_survives_the_cwd_change(
    workdir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    relative = Installation(adapter="pumpkin", target=TARGET, root=Path("cache/pumpkin/26.3"))
    plan = PumpkinAdapter().prepare(relative, ServerSpec(host=HOST, port=25599), workdir)
    assert plan.argv[0] == str(tmp_path / "cache/pumpkin/26.3/pumpkin")


def test_prepare_creates_a_missing_workdir(installation: Installation, tmp_path: Path) -> None:
    workdir = tmp_path / "runs/1/work"
    PumpkinAdapter().prepare(installation, ServerSpec(host=HOST, port=25599), workdir)
    assert (workdir / "pumpkin.toml").is_file()


def test_prepare_accepts_an_empty_workdir(installation: Installation, workdir: Path) -> None:
    workdir.mkdir()
    PumpkinAdapter().prepare(installation, ServerSpec(host=HOST, port=25599), workdir)
    assert (workdir / "pumpkin.toml").is_file()


@pytest.mark.parametrize("stale", ["world/level.dat", "data/ops.json", "pumpkin.toml", ".lock"])
def test_prepare_refuses_a_non_empty_workdir_and_leaves_it_alone(
    installation: Installation, workdir: Path, stale: str
) -> None:
    # A reused workdir would carry world, ban, operator or config state into the next
    # Instance.
    (workdir / stale).parent.mkdir(parents=True)
    (workdir / stale).write_bytes(b"stale")
    with pytest.raises(PrepareError, match="not empty"):
        PumpkinAdapter().prepare(installation, ServerSpec(host=HOST, port=25599), workdir)
    files = [p.relative_to(workdir).as_posix() for p in workdir.rglob("*") if p.is_file()]
    assert (files, (workdir / stale).read_bytes()) == ([stale], b"stale")


@pytest.mark.parametrize(
    "spec",
    [
        ServerSpec(host=HOST, port=25599, view_distance=1),
        ServerSpec(host=HOST, port=25599, operators=("\ud800",)),
    ],
)
def test_a_spec_pumpkin_cannot_read_writes_nothing(
    installation: Installation, workdir: Path, spec: ServerSpec
) -> None:
    with pytest.raises(PrepareError, match="ServerSpec"):
        PumpkinAdapter().prepare(installation, spec, workdir)
    assert nothing_in(workdir)
