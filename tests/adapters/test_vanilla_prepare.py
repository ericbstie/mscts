from pathlib import Path

import pytest

from mscts.adapters.base import Installation, LaunchPlan
from mscts.adapters.vanilla import VanillaAdapter
from mscts.net import Endpoint
from mscts.spec import ServerSpec
from mscts.target import TARGET


@pytest.fixture
def installation(tmp_path: Path) -> Installation:
    return Installation(adapter="vanilla", target=TARGET, root=tmp_path / "cache/vanilla/26.3")


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    return tmp_path / "work"


def test_prepare_accepts_the_eula(installation: Installation, workdir: Path) -> None:
    VanillaAdapter().prepare(installation, ServerSpec(port=25599), workdir)
    assert (workdir / "eula.txt").read_bytes() == b"eula=true\n"


def test_prepare_returns_the_launch_plan(
    installation: Installation, workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", "/opt/jdk-25/bin:/usr/bin")
    plan = VanillaAdapter().prepare(installation, ServerSpec(port=25599), workdir)
    assert plan == LaunchPlan(
        argv=("java", "-Xmx1G", "-jar", str(installation.root / "server.jar"), "nogui"),
        cwd=workdir,
        env={"PATH": "/opt/jdk-25/bin:/usr/bin"},
        endpoint=Endpoint(host="127.0.0.1", port=25599),
        stop_stdin=b"stop\n",
    )


def test_launch_env_passes_only_path_through(
    installation: Installation, workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # This container injects proxy settings through JAVA_TOOL_OPTIONS; none may reach the server.
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", "-Dhttps.proxyHost=127.0.0.1")
    monkeypatch.setenv("LANG", "tr_TR.UTF-8")
    plan = VanillaAdapter().prepare(installation, ServerSpec(port=25599), workdir)
    assert set(plan.env) == {"PATH"}


def test_jar_path_is_absolute_so_it_survives_the_cwd_change(
    workdir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    relative = Installation(adapter="vanilla", target=TARGET, root=Path("cache/vanilla/26.3"))
    plan = VanillaAdapter().prepare(relative, ServerSpec(port=25599), workdir)
    assert plan.argv[3] == str(tmp_path / "cache/vanilla/26.3/server.jar")
