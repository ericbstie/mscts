from pathlib import Path

import pytest

from mscts.adapters.base import Installation, LaunchPlan
from mscts.adapters.vanilla import VanillaAdapter
from mscts.net import Endpoint
from mscts.spec import ServerSpec
from mscts.target import TARGET

# prepare looks up a Java launcher; a fake Java 25 keeps the unit tier off the host's.
pytestmark = pytest.mark.usefixtures("java_25")


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
    installation: Installation, workdir: Path, monkeypatch: pytest.MonkeyPatch, java_25: Path
) -> None:
    monkeypatch.setenv("PATH", "/opt/jdk-25/bin:/usr/bin")
    plan = VanillaAdapter().prepare(installation, ServerSpec(port=25599), workdir)
    assert plan == LaunchPlan(
        argv=(
            str(java_25.resolve()),
            "-Xmx1G",
            "-Dminecraft.api.discovery.host=http://127.0.0.1:0/",
            "-Djdk.net.hosts.file=/dev/null",
            "-jar",
            str(installation.root / "server.jar"),
            "nogui",
        ),
        cwd=workdir,
        env={"PATH": "/opt/jdk-25/bin:/usr/bin"},
        endpoint=Endpoint(host="127.0.0.1", port=25599),
        stop_stdin=b"stop\n",
    )


def test_jvm_is_cut_off_from_every_network_but_loopback(
    installation: Installation, workdir: Path
) -> None:
    # Verified with strace (docs/research/2026-09-25-domain.md): with these two properties
    # vanilla 26.3's only non-UNIX connect is a refused one to 127.0.0.1:0, and it never
    # opens the OS resolver's files.
    argv = VanillaAdapter().prepare(installation, ServerSpec(port=25599), workdir).argv
    jvm_options = argv[1 : argv.index("-jar")]
    assert "-Dminecraft.api.discovery.host=http://127.0.0.1:0/" in jvm_options
    assert "-Djdk.net.hosts.file=/dev/null" in jvm_options


def test_minecraft_api_env_is_never_set(installation: Installation, workdir: Path) -> None:
    # authlib prefers minecraft.api.env (prod/staging) over minecraft.api.discovery.host.
    argv = VanillaAdapter().prepare(installation, ServerSpec(port=25599), workdir).argv
    assert not [arg for arg in argv if arg.startswith("-Dminecraft.api.env")]


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
    assert plan.argv[plan.argv.index("-jar") + 1] == str(tmp_path / "cache/vanilla/26.3/server.jar")
