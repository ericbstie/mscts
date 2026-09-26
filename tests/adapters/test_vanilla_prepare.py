from pathlib import Path

import pytest

from mscts.adapters.base import Installation, LaunchPlan, PrepareError
from mscts.adapters.vanilla import LAUNCH_ENV, VanillaAdapter
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
    installation: Installation, workdir: Path, java_25: Path
) -> None:
    plan = VanillaAdapter().prepare(installation, ServerSpec(port=25599), workdir)
    assert plan == LaunchPlan(
        argv=(
            str(java_25.resolve()),
            "-Xmx1G",
            "-Dminecraft.api.discovery.host=http://127.0.0.1:0/",
            "-Djdk.net.hosts.file=/dev/null",
            "-Duser.timezone=UTC",
            "-Djava.net.preferIPv4Stack=true",
            "-jar",
            str(installation.root / "server.jar"),
            "nogui",
        ),
        cwd=workdir,
        env=dict(LAUNCH_ENV),
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


def test_host_independence_flags_are_set(installation: Installation, workdir: Path) -> None:
    # Verified live (docs/research/2026-09-25-domain.md, "Host independence of the
    # launch"): these keep the Reference's clock and address-family choice off the host.
    argv = VanillaAdapter().prepare(installation, ServerSpec(port=25599), workdir).argv
    jvm_options = argv[1 : argv.index("-jar")]
    assert "-Duser.timezone=UTC" in jvm_options
    assert "-Djava.net.preferIPv4Stack=true" in jvm_options


def test_host_independence_flags_come_after_no_network_flags(
    installation: Installation, workdir: Path
) -> None:
    # Documented argv order: HEAP, then NO_NETWORK (established first), then
    # HOST_INDEPENDENCE, then -jar. The two tables are independent, but a fixed order keeps
    # the golden argv test above meaningful and the LaunchPlan reproducible.
    argv = VanillaAdapter().prepare(installation, ServerSpec(port=25599), workdir).argv
    jvm_options = argv[1 : argv.index("-jar")]
    assert jvm_options.index("-Djdk.net.hosts.file=/dev/null") < jvm_options.index(
        "-Duser.timezone=UTC"
    )


def test_launch_env_is_fixed_and_never_leaks_the_harness(
    installation: Installation, workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The env must not depend on the harness at all, so the Reference's behaviour cannot
    # depend on who launches it or from where. Not PATH (argv[0] is already the resolved,
    # absolute java launcher); not JAVA_TOOL_OPTIONS (this container injects proxy settings
    # through it); not locale variables.
    monkeypatch.setenv("PATH", "/some/harness/shims:/usr/bin")
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", "-Dhttps.proxyHost=127.0.0.1")
    monkeypatch.setenv("LANG", "tr_TR.UTF-8")
    plan = VanillaAdapter().prepare(installation, ServerSpec(port=25599), workdir)
    assert plan.env == dict(LAUNCH_ENV)


def test_jar_path_is_absolute_so_it_survives_the_cwd_change(
    workdir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    relative = Installation(adapter="vanilla", target=TARGET, root=Path("cache/vanilla/26.3"))
    plan = VanillaAdapter().prepare(relative, ServerSpec(port=25599), workdir)
    assert plan.argv[plan.argv.index("-jar") + 1] == str(tmp_path / "cache/vanilla/26.3/server.jar")


def test_prepare_creates_a_missing_workdir(installation: Installation, tmp_path: Path) -> None:
    workdir = tmp_path / "runs/1/work"
    VanillaAdapter().prepare(installation, ServerSpec(port=25599), workdir)
    assert (workdir / "server.properties").is_file()


def test_prepare_accepts_an_empty_workdir(installation: Installation, workdir: Path) -> None:
    workdir.mkdir()
    VanillaAdapter().prepare(installation, ServerSpec(port=25599), workdir)
    assert (workdir / "server.properties").is_file()


@pytest.mark.parametrize("stale", ["world/level.dat", "banned-players.json", ".lock"])
def test_prepare_refuses_a_non_empty_workdir_and_leaves_it_alone(
    installation: Installation, workdir: Path, stale: str
) -> None:
    # A reused workdir would carry world, ban or icon state into the next Instance.
    (workdir / stale).parent.mkdir(parents=True)
    (workdir / stale).write_bytes(b"stale")
    with pytest.raises(PrepareError, match="not empty"):
        VanillaAdapter().prepare(installation, ServerSpec(port=25599), workdir)
    files = [p.relative_to(workdir).as_posix() for p in workdir.rglob("*") if p.is_file()]
    assert (files, (workdir / stale).read_bytes()) == ([stale], b"stale")
