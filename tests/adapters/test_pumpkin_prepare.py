from pathlib import Path
from types import MappingProxyType

import pytest

from mscts.adapters import pumpkin
from mscts.adapters.base import Adapter, Installation, LaunchPlan, PrepareError
from mscts.adapters.pumpkin import PumpkinAdapter, ops_json, pumpkin_toml
from mscts.net import Endpoint
from mscts.spec import Difficulty, ServerSpec
from mscts.target import TARGET


@pytest.fixture
def installation(tmp_path: Path) -> Installation:
    return Installation(adapter="pumpkin", target=TARGET, root=tmp_path / "cache/pumpkin/26.3")


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    return tmp_path / "work"


@pytest.fixture
def if_pumpkin_honoured_every_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lift pumpkin.LIMITS, to test the rest of prepare: no ServerSpec gets past it yet."""
    monkeypatch.setattr(pumpkin, "LIMITS", MappingProxyType({}))


def nothing_in(workdir: Path) -> bool:
    return not workdir.exists() or not any(workdir.iterdir())


# The limits of the nightly (docs/research/2026-09-26-pumpkin.md, "World and difficulty").


def test_prepare_refuses_a_flat_world_and_writes_nothing(
    installation: Installation, workdir: Path
) -> None:
    spec = ServerSpec(port=25599, difficulty=Difficulty.NORMAL)
    with pytest.raises(PrepareError, match=r"ServerSpec\.world=flat") as refusal:
        PumpkinAdapter().prepare(installation, spec, workdir)
    assert "ServerSpec.difficulty" not in str(refusal.value)
    assert nothing_in(workdir)


@pytest.mark.parametrize("level", [Difficulty.PEACEFUL, Difficulty.EASY, Difficulty.HARD])
def test_prepare_refuses_a_difficulty_other_than_normal(
    installation: Installation, workdir: Path, level: Difficulty
) -> None:
    spec = ServerSpec(port=25599, difficulty=level)
    with pytest.raises(PrepareError, match=rf"ServerSpec\.difficulty={level}"):
        PumpkinAdapter().prepare(installation, spec, workdir)
    assert nothing_in(workdir)


def test_every_field_pumpkin_cannot_honour_is_named_at_once(
    installation: Installation, workdir: Path
) -> None:
    with pytest.raises(PrepareError) as refusal:
        PumpkinAdapter().prepare(installation, ServerSpec(port=25599), workdir)
    assert "ServerSpec.world=flat" in str(refusal.value)
    assert "ServerSpec.difficulty=peaceful" in str(refusal.value)


# The rest of prepare, as it would run if Pumpkin could honour every ServerSpec.

if_honoured = pytest.mark.usefixtures("if_pumpkin_honoured_every_spec")


@if_honoured
def test_pumpkin_is_an_adapter(installation: Installation, workdir: Path) -> None:
    adapter: Adapter = PumpkinAdapter()
    assert adapter.name == "pumpkin"
    adapter.prepare(installation, ServerSpec(port=25599), workdir)


@if_honoured
def test_prepare_writes_the_complete_config(installation: Installation, workdir: Path) -> None:
    spec = ServerSpec(port=25599, operators=("Notch",))
    PumpkinAdapter().prepare(installation, spec, workdir)
    written = {
        path.relative_to(workdir).as_posix(): path.read_text(encoding="utf-8")
        for path in workdir.rglob("*")
        if path.is_file()
    }
    assert written == {
        "pumpkin.toml": pumpkin_toml(spec),
        "data/ops.json": ops_json(("Notch",)),
        # Pumpkin's own first-run content of each; no ServerSpec field changes them.
        "data/whitelist.json": "[]",
        "data/banned-players.json": "[]",
        "data/banned-ips.json": "[]",
    }


@if_honoured
def test_prepare_returns_the_launch_plan(installation: Installation, workdir: Path) -> None:
    plan = PumpkinAdapter().prepare(installation, ServerSpec(port=25599), workdir)
    assert plan == LaunchPlan(
        argv=(str(installation.root / "pumpkin"),),  # it takes no arguments
        cwd=workdir,
        env={},
        endpoint=Endpoint(host="127.0.0.1", port=25599),
        stop_stdin=b"stop\n",
    )


@if_honoured
def test_nothing_from_the_harness_environment_reaches_pumpkin(
    installation: Installation, workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Pumpkin reads RUST_LOG (its log filter) and, through reqwest, the proxy variables.
    monkeypatch.setenv("RUST_LOG", "trace")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:3128")
    plan = PumpkinAdapter().prepare(installation, ServerSpec(port=25599), workdir)
    assert dict(plan.env) == {}


@if_honoured
def test_the_binary_path_is_absolute_so_it_survives_the_cwd_change(
    workdir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    relative = Installation(adapter="pumpkin", target=TARGET, root=Path("cache/pumpkin/26.3"))
    plan = PumpkinAdapter().prepare(relative, ServerSpec(port=25599), workdir)
    assert plan.argv[0] == str(tmp_path / "cache/pumpkin/26.3/pumpkin")


@if_honoured
def test_prepare_creates_a_missing_workdir(installation: Installation, tmp_path: Path) -> None:
    workdir = tmp_path / "runs/1/work"
    PumpkinAdapter().prepare(installation, ServerSpec(port=25599), workdir)
    assert (workdir / "pumpkin.toml").is_file()


@if_honoured
def test_prepare_accepts_an_empty_workdir(installation: Installation, workdir: Path) -> None:
    workdir.mkdir()
    PumpkinAdapter().prepare(installation, ServerSpec(port=25599), workdir)
    assert (workdir / "pumpkin.toml").is_file()


@if_honoured
@pytest.mark.parametrize("stale", ["world/level.dat", "data/ops.json", "pumpkin.toml", ".lock"])
def test_prepare_refuses_a_non_empty_workdir_and_leaves_it_alone(
    installation: Installation, workdir: Path, stale: str
) -> None:
    # A reused workdir would carry world, ban, operator or config state into the next
    # Instance.
    (workdir / stale).parent.mkdir(parents=True)
    (workdir / stale).write_bytes(b"stale")
    with pytest.raises(PrepareError, match="not empty"):
        PumpkinAdapter().prepare(installation, ServerSpec(port=25599), workdir)
    files = [p.relative_to(workdir).as_posix() for p in workdir.rglob("*") if p.is_file()]
    assert (files, (workdir / stale).read_bytes()) == ([stale], b"stale")


@if_honoured
@pytest.mark.parametrize(
    "spec", [ServerSpec(port=25599, view_distance=1), ServerSpec(port=25599, operators=("\ud800",))]
)
def test_a_spec_pumpkin_cannot_read_writes_nothing(
    installation: Installation, workdir: Path, spec: ServerSpec
) -> None:
    with pytest.raises(PrepareError, match="ServerSpec"):
        PumpkinAdapter().prepare(installation, spec, workdir)
    assert nothing_in(workdir)
