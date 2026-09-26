import datetime
import hashlib
import json
from pathlib import Path

import pytest

from mscts.adapters.base import Installation, ProvisionError
from mscts.adapters.fetch import Download
from mscts.adapters.pumpkin import NIGHTLY_URL, PumpkinAdapter
from mscts.target import TARGET

ASSET_URL = "https://release-assets.githubusercontent.com/github-production-release-asset/1/2?sig=s"
# A stand-in for the binary: an ELF header, then filler. Never run.
FAKE_BINARY = b"\x7fELF\x02\x01\x01\x00" + bytes(range(256)) * 4


class FakeGitHub:
    """A fetch that serves one release asset (after a redirect) and records every URL asked."""

    def __init__(self, body: bytes = FAKE_BINARY) -> None:
        self.body = body
        self.fetched: list[str] = []

    def __call__(self, url: str) -> Download:
        self.fetched.append(url)
        return Download(url=ASSET_URL, body=self.body)


def root_of(cache: Path) -> Path:
    return cache / "pumpkin/26.3"


def test_provision_downloads_the_nightly_into_the_cache(tmp_path: Path) -> None:
    github = FakeGitHub()
    adapter = PumpkinAdapter(fetch=github)
    installation = adapter.provision(TARGET, tmp_path)
    assert installation == Installation(adapter="pumpkin", target=TARGET, root=root_of(tmp_path))
    assert (installation.root / "pumpkin").read_bytes() == FAKE_BINARY
    assert github.fetched == [NIGHTLY_URL]


def test_the_nightly_url_is_the_linux_x64_release_asset() -> None:
    assert NIGHTLY_URL == (
        "https://github.com/Pumpkin-MC/Pumpkin/releases/download/nightly/pumpkin-X64-Linux"
    )


def test_the_binary_is_executable(tmp_path: Path) -> None:
    installation = PumpkinAdapter(fetch=FakeGitHub()).provision(TARGET, tmp_path)
    assert (installation.root / "pumpkin").stat().st_mode & 0o777 == 0o755


def test_source_json_records_what_was_fetched_from_where_and_when(tmp_path: Path) -> None:
    # No hash is published for the nightly, so the Installation records its own.
    before = datetime.datetime.now(datetime.UTC).replace(microsecond=0)
    installation = PumpkinAdapter(fetch=FakeGitHub()).provision(TARGET, tmp_path)
    after = datetime.datetime.now(datetime.UTC)
    source = json.loads((installation.root / "SOURCE.json").read_text(encoding="utf-8"))
    fetched_at = datetime.datetime.fromisoformat(source.pop("fetched_at"))
    assert source == {
        "url": NIGHTLY_URL,
        "final_url": ASSET_URL,
        "sha256": hashlib.sha256(FAKE_BINARY).hexdigest(),
        "size": len(FAKE_BINARY),
    }
    assert before <= fetched_at <= after
    assert fetched_at.tzinfo == datetime.UTC


def test_the_installation_holds_nothing_but_the_binary_and_its_record(tmp_path: Path) -> None:
    installation = PumpkinAdapter(fetch=FakeGitHub()).provision(TARGET, tmp_path)
    assert sorted(p.name for p in installation.root.iterdir()) == ["SOURCE.json", "pumpkin"]
    assert sorted(p.name for p in (tmp_path / "pumpkin").iterdir()) == ["26.3"]


def test_provision_reuses_the_cached_binary(tmp_path: Path) -> None:
    PumpkinAdapter(fetch=FakeGitHub()).provision(TARGET, tmp_path)
    binary = root_of(tmp_path) / "pumpkin"
    before = binary.stat()
    again = FakeGitHub(body=b"\x7fELF a newer nightly")
    installation = PumpkinAdapter(fetch=again).provision(TARGET, tmp_path)
    assert again.fetched == []
    assert installation.root == root_of(tmp_path)
    after = binary.stat()
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)


def test_provision_refuses_a_cached_binary_that_differs_from_its_record(tmp_path: Path) -> None:
    PumpkinAdapter(fetch=FakeGitHub()).provision(TARGET, tmp_path)
    binary = root_of(tmp_path) / "pumpkin"
    tampered = bytearray(binary.read_bytes())
    tampered[-1] ^= 0xFF
    binary.write_bytes(bytes(tampered))
    github = FakeGitHub()
    with pytest.raises(ProvisionError, match="sha256"):
        PumpkinAdapter(fetch=github).provision(TARGET, tmp_path)
    assert github.fetched == []  # never silently replaced by whatever the nightly is today


def test_provision_refuses_a_download_that_is_not_an_elf_executable(tmp_path: Path) -> None:
    with pytest.raises(ProvisionError, match="ELF"):
        PumpkinAdapter(fetch=FakeGitHub(body=b"<!DOCTYPE html>")).provision(TARGET, tmp_path)
    assert not root_of(tmp_path).exists()


def test_a_failed_download_leaves_no_installation_behind(tmp_path: Path) -> None:
    def failing(url: str) -> Download:
        msg = f"connection reset fetching {url}"
        raise OSError(msg)

    with pytest.raises(OSError, match="connection reset"):
        PumpkinAdapter(fetch=failing).provision(TARGET, tmp_path)
    assert not root_of(tmp_path).exists()


def test_a_concurrent_provision_that_finishes_first_wins(tmp_path: Path) -> None:
    # Another session installs the nightly while this one is still downloading.
    theirs = FakeGitHub()

    def slower(url: str) -> Download:
        PumpkinAdapter(fetch=theirs).provision(TARGET, tmp_path)
        return Download(url=url, body=b"\x7fELF a newer nightly")

    installation = PumpkinAdapter(fetch=slower).provision(TARGET, tmp_path)
    assert (installation.root / "pumpkin").read_bytes() == FAKE_BINARY
    assert sorted(p.name for p in (tmp_path / "pumpkin").iterdir()) == ["26.3"]


def test_installation_root_is_absolute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    installation = PumpkinAdapter(fetch=FakeGitHub()).provision(TARGET, Path("cache"))
    assert installation.root == tmp_path / "cache/pumpkin/26.3"
