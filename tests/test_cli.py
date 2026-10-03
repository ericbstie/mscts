import hashlib
import json
import tomllib
from pathlib import Path

import pytest
from support.pumpkin import COMMIT, FakeGitHub, fake_pumpkin

from mscts.adapters.pumpkin import NIGHTLY_URL, TAGS_URL
from mscts.cli import main

BUILD = fake_pumpkin()
SHA256 = hashlib.sha256(BUILD).hexdigest()


@pytest.fixture
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty cache."""
    monkeypatch.setenv("MSCTS_CACHE", str(tmp_path / "cache"))
    return tmp_path / "cache"


def run(
    capsys: pytest.CaptureFixture[str], *argv: str, fetch: FakeGitHub | None = None
) -> tuple[int, str, str]:
    code = main(list(argv), fetch=fetch or FakeGitHub())
    out, err = capsys.readouterr()
    return code, out, err


def test_install_downloads_the_latest_build_saying_so_and_says_what_it_did(
    cache: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    github = FakeGitHub()
    code, out, err = run(capsys, "adapter", "install", "pumpkin", fetch=github)
    root = cache / "pumpkin/26.3"
    assert (code, err) == (0, "")
    assert out == (
        f"downloading {TAGS_URL} ...\ndownloading {NIGHTLY_URL} ...\n"
        f"installed pumpkin nightly 4426d11 from {NIGHTLY_URL} into {root}\n"
    )
    assert github.fetched == [TAGS_URL, NIGHTLY_URL]


def test_install_at_a_version_installs_that_build(
    cache: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = run(capsys, "adapter", "install", f"pumpkin@{COMMIT[:7]}")
    assert code == 0
    assert out.endswith(
        f"installed pumpkin nightly 4426d11 from {NIGHTLY_URL} into {cache}/pumpkin/26.3\n"
    )


def test_a_second_install_is_a_no_op_that_says_so(
    cache: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run(capsys, "adapter", "install", "pumpkin")
    github = FakeGitHub()
    code, out, _ = run(capsys, "adapter", "install", "pumpkin@4426d11", fetch=github)
    root = cache / "pumpkin/26.3"
    assert code == 0
    assert out == (
        f"pumpkin nightly 4426d11 is already installed at {root} (sha256 {SHA256}): "
        f"nothing to do. To check for a newer build, delete {root} and install again.\n"
    )
    assert github.fetched == []


@pytest.mark.usefixtures("cache")
def test_an_unpublished_version_fails_saying_how_to_build_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, err = run(capsys, "adapter", "install", "pumpkin@8f3c2a1")
    assert code == 1
    assert out == f"downloading {TAGS_URL} ...\n"
    assert err == (
        "mscts: pumpkin@8f3c2a1 is not available: Pumpkin only publishes its latest nightly "
        "(now 4426d11).\n"
        "Build it yourself and install it with:\n"
        "  uv run mscts adapter install pumpkin --from <file>\n"
    )


@pytest.mark.usefixtures("cache")
def test_another_minecraft_version_is_not_supported(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(capsys, "adapter", "install", "vanilla@26.4")
    assert (code, out) == (1, "")
    assert err == "mscts: vanilla@26.4 is not supported: this mscts tests Minecraft 26.3.\n"


def test_install_from_a_file(
    cache: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    supplied = tmp_path / "pumpkin-X64-Linux"
    supplied.write_bytes(BUILD)
    github = FakeGitHub()
    code, out, _ = run(
        capsys, "adapter", "install", "pumpkin", "--from", str(supplied), fetch=github
    )
    assert code == 0
    assert out == (
        f"installed {supplied} (pumpkin 0.2.0+26.3-26.51 4426d11, sha256 {SHA256}) "
        f"into {cache / 'pumpkin/26.3'}\n"
    )
    assert github.fetched == []


@pytest.mark.usefixtures("cache")
def test_a_version_and_a_file_are_exclusive(capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = run(capsys, "adapter", "install", "pumpkin@4426d11", "--from", "f")
    assert (code, err) == (
        1,
        "mscts: pumpkin@4426d11 --from f: name a version or a file, not both\n",
    )


@pytest.mark.usefixtures("cache")
def test_an_at_without_a_version_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        main(["adapter", "install", "pumpkin@"])
    assert exited.value.code == 2
    assert "pumpkin@ names no version" in capsys.readouterr().err


@pytest.mark.parametrize("argument", ["minestom", "minestom@1", "@26.3"])
@pytest.mark.usefixtures("cache")
def test_an_unknown_adapter_is_a_usage_error(
    capsys: pytest.CaptureFixture[str], argument: str
) -> None:
    with pytest.raises(SystemExit) as exited:
        main(["adapter", "install", argument])
    assert exited.value.code == 2
    assert "the known Adapters are vanilla, pumpkin" in capsys.readouterr().err


@pytest.mark.usefixtures("cache")
def test_the_version_option_is_gone(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        main(["adapter", "install", "pumpkin", "--version", "4426d11"])
    assert exited.value.code == 2
    assert "unrecognized arguments: --version" in capsys.readouterr().err


@pytest.mark.usefixtures("cache")
def test_list_shows_every_adapter_and_what_is_installed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, _ = run(capsys, "adapter", "list")
    assert code == 0
    assert out.splitlines() == [
        "ADAPTER  VERSION  TARGET  STATE",
        "vanilla  -        26.3    not installed",
        "pumpkin  -        26.3    not installed",
    ]
    run(capsys, "adapter", "install", "pumpkin")
    assert run(capsys, "adapter", "list")[1].splitlines()[1:] == [
        "vanilla  -                26.3    not installed",
        "pumpkin  nightly 4426d11  26.3    installed",
    ]


@pytest.mark.usefixtures("cache")
def test_status_of_nothing_installed_names_the_install_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, _ = run(capsys, "adapter", "status", "pumpkin")
    assert (code, out) == (
        1,
        "pumpkin 26.3: not installed. Install it with `mscts adapter install pumpkin`\n",
    )


def test_status_says_what_is_installed_its_sha256_and_source(
    cache: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run(capsys, "adapter", "install", "pumpkin")
    code, out, _ = run(capsys, "adapter", "status", "pumpkin")
    lines = out.splitlines()
    assert code == 0
    assert lines[:6] == [
        f"pumpkin 26.3: installed at {cache / 'pumpkin/26.3'}",
        "  version:   nightly",
        f"  commit:    {COMMIT}",
        f"  sha256:    {SHA256}",
        f"  size:      {len(BUILD)} bytes",
        f"  from:      {NIGHTLY_URL}",
    ]
    assert lines[6].startswith("  installed: 20")


def test_status_of_a_build_without_a_commit_leaves_the_commit_out(
    cache: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    supplied = tmp_path / "mine"
    supplied.write_bytes(fake_pumpkin(commit="unknown"))
    run(capsys, "adapter", "install", "pumpkin", "--from", str(supplied))
    lines = run(capsys, "adapter", "status", "pumpkin")[1].splitlines()
    assert lines[1:3] == [
        "  version:   0.2.0+26.3-26.51",
        f"  sha256:    {hashlib.sha256(supplied.read_bytes()).hexdigest()}",
    ]
    assert lines[4] == f"  from:      {supplied}"
    assert cache.exists()


def test_status_of_a_changed_binary_fails_naming_the_fix(
    cache: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run(capsys, "adapter", "install", "pumpkin")
    (cache / "pumpkin/26.3/pumpkin").write_bytes(BUILD + b"!")
    code, _, err = run(capsys, "adapter", "status", "pumpkin")
    assert code == 1
    assert f"delete {cache / 'pumpkin/26.3'} and run `mscts adapter install pumpkin` again" in err
    assert "unusable: see `mscts adapter status pumpkin`" in run(capsys, "adapter", "list")[1]


def test_status_names_the_build_of_an_installation_recorded_before_builds_were(
    cache: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = cache / "pumpkin/26.3"
    root.mkdir(parents=True)
    (root / "pumpkin").write_bytes(BUILD)
    legacy = {"sha256": SHA256, "size": len(BUILD), "entry": "pumpkin nightly-b8382a8a"}
    (root / "SOURCE.json").write_text(json.dumps(legacy))
    code, out, _ = run(capsys, "adapter", "status", "pumpkin")
    assert code == 0
    assert out.splitlines()[1:3] == ["  version:   0.2.0+26.3-26.51", f"  commit:    {COMMIT}"]


def test_the_mscts_script_is_the_cli() -> None:
    pyproject = tomllib.loads(Path(__file__).parent.parent.joinpath("pyproject.toml").read_text())
    assert pyproject["project"]["scripts"] == {"mscts": "mscts.cli:main"}
