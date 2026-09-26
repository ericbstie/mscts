import hashlib
import tomllib
from pathlib import Path

import pytest

from mscts import registry
from mscts.adapters.fetch import Download
from mscts.cli import main
from mscts.registry import Entry, Registry

URL = "https://github.com/Pumpkin-MC/Pumpkin/releases/download/nightly/pumpkin-X64-Linux"
BUILD = b"\x7fELF\x02\x01\x01\x00 a pinned build"
SHA256 = hashlib.sha256(BUILD).hexdigest()
ENTRY = Entry(
    adapter="pumpkin",
    version="nightly-test",
    target="26.3",
    url=URL,
    sha256=SHA256,
    note="The nightly URL moves: a mismatch means the nightly moved.",
)


class FakeGitHub:
    def __init__(self, body: bytes = BUILD) -> None:
        self.body = body
        self.fetched: list[str] = []

    def __call__(self, url: str) -> Download:
        self.fetched.append(url)
        return Download(url=url, body=self.body)


@pytest.fixture
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty cache and a Registry of ENTRY alone (and no vanilla entry)."""
    monkeypatch.setenv("MSCTS_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(registry, "official", lambda: Registry(entries=(ENTRY,)))
    return tmp_path / "cache"


def run(
    capsys: pytest.CaptureFixture[str], *argv: str, fetch: FakeGitHub | None = None
) -> tuple[int, str, str]:
    code = main(list(argv), fetch=fetch or FakeGitHub())
    out, err = capsys.readouterr()
    return code, out, err


def test_install_downloads_saying_so_and_says_what_it_did(
    cache: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    github = FakeGitHub()
    code, out, err = run(capsys, "adapter", "install", "pumpkin", fetch=github)
    root = cache / "pumpkin/26.3"
    assert (code, err) == (0, "")
    assert out == (
        f"downloading {URL} ...\ninstalled pumpkin nightly-test from {URL} into {root}\n"
    )
    assert github.fetched == [URL]


def test_a_second_install_is_a_no_op_that_says_so(
    cache: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run(capsys, "adapter", "install", "pumpkin")
    github = FakeGitHub()
    code, out, _ = run(
        capsys, "adapter", "install", "pumpkin", "--version", "nightly-test", fetch=github
    )
    assert code == 0
    assert out == (
        f"pumpkin nightly-test is already installed at {cache / 'pumpkin/26.3'} "
        f"(sha256 {SHA256}): nothing to do\n"
    )
    assert github.fetched == []


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
        f"installed {supplied} (sha256 {SHA256}; the Registry entry pumpkin nightly-test) "
        f"into {cache / 'pumpkin/26.3'}\n"
    )
    assert github.fetched == []


def test_a_moved_nightly_fails_naming_the_fix(
    cache: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, err = run(capsys, "adapter", "install", "pumpkin", fetch=FakeGitHub(b"\x7fELF newer"))
    assert code == 1
    assert err.startswith(f"mscts: {URL} is not pumpkin nightly-test: sha256 ")
    assert "the nightly moved" in err
    assert "`mscts adapter install pumpkin --from <file>`" in err
    assert not cache.exists() or not (cache / "pumpkin/26.3").exists()


@pytest.mark.usefixtures("cache")
def test_an_unknown_version_fails_naming_the_entries(capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = run(capsys, "adapter", "install", "pumpkin", "--version", "nightly-old")
    assert (code, err) == (
        1,
        "mscts: pumpkin has no registry entry nightly-old; its entries: nightly-test\n",
    )


@pytest.mark.usefixtures("cache")
def test_version_and_from_are_exclusive(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        main(["adapter", "install", "pumpkin", "--version", "v", "--from", "f"])
    assert exited.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


@pytest.mark.usefixtures("cache")
def test_list_shows_every_adapter_entry_and_install_state(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, _ = run(capsys, "adapter", "list")
    assert code == 0
    assert out.splitlines() == [
        "ADAPTER  VERSION       TARGET  STATE",
        "vanilla  -             -       no Registry entry; install one with --from",
        "pumpkin  nightly-test  26.3    not installed",
    ]
    run(capsys, "adapter", "install", "pumpkin")
    assert run(capsys, "adapter", "list")[1].splitlines()[2] == (
        "pumpkin  nightly-test  26.3    installed"
    )


@pytest.mark.usefixtures("cache")
def test_list_shows_a_from_build_that_is_no_entry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    supplied = tmp_path / "mine"
    supplied.write_bytes(b"\x7fELF my build")
    run(capsys, "adapter", "install", "pumpkin", "--from", str(supplied))
    sha256 = hashlib.sha256(b"\x7fELF my build").hexdigest()
    assert run(capsys, "adapter", "list")[1].splitlines()[2:] == [
        "pumpkin  nightly-test  26.3    not installed",
        (
            f"pumpkin  -             26.3    installed: no Registry entry, from {supplied} "
            f"(sha256 {sha256})"
        ),
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
    cache: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    supplied = tmp_path / "pumpkin-X64-Linux"
    supplied.write_bytes(BUILD)
    run(capsys, "adapter", "install", "pumpkin", "--from", str(supplied))
    code, out, _ = run(capsys, "adapter", "status", "pumpkin")
    lines = out.splitlines()
    assert code == 0
    assert lines[:5] == [
        f"pumpkin 26.3: installed at {cache / 'pumpkin/26.3'}",
        "  entry:     pumpkin nightly-test",
        f"  sha256:    {SHA256}",
        f"  size:      {len(BUILD)} bytes",
        f"  from:      {supplied}",
    ]
    assert lines[5].startswith("  installed: 20")


def test_status_of_a_changed_binary_fails_naming_the_fix(
    cache: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run(capsys, "adapter", "install", "pumpkin")
    (cache / "pumpkin/26.3/pumpkin").write_bytes(BUILD + b"!")
    code, _, err = run(capsys, "adapter", "status", "pumpkin")
    assert code == 1
    assert f"delete {cache / 'pumpkin/26.3'} and run `mscts adapter install pumpkin` again" in err
    assert "unusable: see `mscts adapter status pumpkin`" in run(capsys, "adapter", "list")[1]


def test_the_mscts_script_is_the_cli() -> None:
    pyproject = tomllib.loads(Path(__file__).parent.parent.joinpath("pyproject.toml").read_text())
    assert pyproject["project"]["scripts"] == {"mscts": "mscts.cli:main"}
