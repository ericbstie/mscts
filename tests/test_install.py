import dataclasses
import datetime
import hashlib
import json
import logging
from pathlib import Path

import pytest

from mscts import install, registry
from mscts.adapters.base import Installation, ProvisionError, Source
from mscts.adapters.fetch import Download
from mscts.adapters.pumpkin import PumpkinAdapter
from mscts.install import install_entry, install_from, installed
from mscts.registry import Entry, Registry
from mscts.target import TARGET

URL = "https://github.com/Pumpkin-MC/Pumpkin/releases/download/nightly/pumpkin-X64-Linux"
ASSET_URL = "https://release-assets.githubusercontent.com/github-production-release-asset/1/2?sig=s"
# A stand-in for the binary: an ELF header, then filler. Never run.
FAKE_BINARY = b"\x7fELF\x02\x01\x01\x00" + bytes(range(256)) * 4
ENTRY = Entry(
    adapter="pumpkin",
    version="nightly-test",
    target="26.3",
    url=URL,
    sha256=hashlib.sha256(FAKE_BINARY).hexdigest(),
    note="The nightly URL moves: a mismatch means the nightly moved.",
)
REGISTRY = Registry(entries=(ENTRY,))
ADAPTER = PumpkinAdapter()


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


def recorded(cache: Path) -> dict[str, object]:
    source: object = json.loads((root_of(cache) / "SOURCE.json").read_text(encoding="utf-8"))
    assert isinstance(source, dict)
    return {str(key): value for key, value in source.items()}


def test_install_entry_downloads_verifies_and_records_it(tmp_path: Path) -> None:
    github = FakeGitHub()
    before = datetime.datetime.now(datetime.UTC).replace(microsecond=0)
    done = install_entry(ADAPTER, TARGET, tmp_path, ENTRY, github)
    assert github.fetched == [URL]
    assert done.changed
    assert done.message == (f"installed pumpkin nightly-test from {URL} into {root_of(tmp_path)}")
    source = recorded(tmp_path)
    installed_at = datetime.datetime.fromisoformat(str(source.pop("installed_at")))
    assert before <= installed_at <= datetime.datetime.now(datetime.UTC)
    assert source == {
        "sha256": ENTRY.sha256,
        "size": len(FAKE_BINARY),
        "entry": "pumpkin nightly-test",
        "url": URL,
        "final_url": ASSET_URL,
        "from_path": None,
    }
    assert done.installation == Installation(
        adapter="pumpkin",
        target=TARGET,
        root=root_of(tmp_path),
        source=Source(
            sha256=str(ENTRY.sha256),
            size=len(FAKE_BINARY),
            entry="pumpkin nightly-test",
            url=URL,
            final_url=ASSET_URL,
            installed_at=installed_at.isoformat(),
        ),
    )
    binary = root_of(tmp_path) / "pumpkin"
    assert binary.read_bytes() == FAKE_BINARY
    assert binary.stat().st_mode & 0o777 == 0o755
    assert sorted(p.name for p in root_of(tmp_path).iterdir()) == ["SOURCE.json", "pumpkin"]
    assert sorted(p.name for p in (tmp_path / "pumpkin").iterdir()) == ["26.3"]


def test_installing_an_installed_entry_again_is_a_no_op_that_says_so(tmp_path: Path) -> None:
    install_entry(ADAPTER, TARGET, tmp_path, ENTRY, FakeGitHub())
    binary = root_of(tmp_path) / "pumpkin"
    before = binary.stat()
    again = FakeGitHub()
    done = install_entry(ADAPTER, TARGET, tmp_path, ENTRY, again)
    assert again.fetched == []
    assert not done.changed
    assert done.message == (
        f"pumpkin nightly-test is already installed at {root_of(tmp_path)} "
        f"(sha256 {ENTRY.sha256}): nothing to do"
    )
    after = binary.stat()
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)


def test_a_download_that_is_not_the_entry_says_the_nightly_moved_and_names_the_fix(
    tmp_path: Path,
) -> None:
    moved = b"\x7fELF a newer nightly"
    with pytest.raises(ProvisionError) as raised:
        install_entry(ADAPTER, TARGET, tmp_path, ENTRY, FakeGitHub(body=moved))
    message = str(raised.value)
    assert f"sha256 {hashlib.sha256(moved).hexdigest()}" in message
    assert "the nightly moved" in message
    assert "`mscts adapter install pumpkin --from <file>`" in message
    assert not root_of(tmp_path).exists()


def test_an_entry_for_another_adapter_or_target_is_refused(tmp_path: Path) -> None:
    for entry in (
        dataclasses.replace(ENTRY, adapter="vanilla"),
        dataclasses.replace(ENTRY, target="26.2"),
    ):
        with pytest.raises(ProvisionError, match=r"not pumpkin 26\.3"):
            install_entry(ADAPTER, TARGET, tmp_path, entry, FakeGitHub())


def test_a_download_that_is_not_an_elf_executable_is_refused(tmp_path: Path) -> None:
    html = b"<!DOCTYPE html>"
    entry = dataclasses.replace(ENTRY, sha256=hashlib.sha256(html).hexdigest())
    with pytest.raises(ProvisionError, match="ELF"):
        install_entry(ADAPTER, TARGET, tmp_path, entry, FakeGitHub(body=html))
    assert not root_of(tmp_path).exists()
    assert list((tmp_path / "pumpkin").iterdir()) == []  # no staging directory left


def test_a_failed_download_leaves_no_installation_behind(tmp_path: Path) -> None:
    def failing(url: str) -> Download:
        msg = f"connection reset fetching {url}"
        raise OSError(msg)

    with pytest.raises(ProvisionError, match=r"connection reset(.|\n)*--from <file>"):
        install_entry(ADAPTER, TARGET, tmp_path, ENTRY, failing)
    assert not root_of(tmp_path).exists()


def test_a_concurrent_install_that_finishes_first_wins(tmp_path: Path) -> None:
    def slower(url: str) -> Download:
        install_entry(ADAPTER, TARGET, tmp_path, ENTRY, FakeGitHub())  # another session
        return Download(url=url, body=FAKE_BINARY)

    done = install_entry(ADAPTER, TARGET, tmp_path, ENTRY, slower)
    assert done.installation.root == root_of(tmp_path)
    assert sorted(p.name for p in (tmp_path / "pumpkin").iterdir()) == ["26.3"]


def test_an_installation_whose_binary_changed_is_refused_naming_the_fix(tmp_path: Path) -> None:
    install_entry(ADAPTER, TARGET, tmp_path, ENTRY, FakeGitHub())
    binary = root_of(tmp_path) / "pumpkin"
    binary.write_bytes(FAKE_BINARY + b"!")
    github = FakeGitHub()
    with pytest.raises(ProvisionError) as raised:
        install_entry(ADAPTER, TARGET, tmp_path, ENTRY, github)
    assert f"is not the recorded {ENTRY.sha256}" in str(raised.value)
    assert f"delete {root_of(tmp_path)} and run `mscts adapter install pumpkin` again" in str(
        raised.value
    )
    assert github.fetched == []  # never silently replaced


def test_an_unrecorded_installation_is_refused_naming_the_fix(tmp_path: Path) -> None:
    root_of(tmp_path).mkdir(parents=True)
    with pytest.raises(ProvisionError, match=r"not a recorded Installation.*delete"):
        installed(ADAPTER, TARGET, tmp_path)


def test_an_unrecorded_installation_of_a_registry_build_is_recorded_as_that_entry_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Installations made before SOURCE.json existed hold the binary alone.
    monkeypatch.setattr(registry, "official", lambda: REGISTRY)
    root_of(tmp_path).mkdir(parents=True)
    (root_of(tmp_path) / "pumpkin").write_bytes(FAKE_BINARY)
    with caplog.at_level(logging.WARNING, logger="mscts.install"):
        found = installed(ADAPTER, TARGET, tmp_path)
    root = root_of(tmp_path)
    said = (
        f"recorded {root / 'SOURCE.json'}: {root / 'pumpkin'} predates recorded sources "
        "and hash-matches the Registry entry pumpkin nightly-test"
    )
    assert [r.getMessage() for r in caplog.records] == [said]
    assert found is not None
    assert found.source is not None
    assert found.source == Source(
        sha256=str(ENTRY.sha256), size=len(FAKE_BINARY), entry="pumpkin nightly-test"
    )
    assert sorted(p.name for p in root_of(tmp_path).iterdir()) == ["SOURCE.json", "pumpkin"]
    assert "found in the cache and matched by hash" in install.describe(found.source)


def test_an_unrecorded_installation_of_an_unknown_build_stays_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(registry, "official", lambda: REGISTRY)
    root_of(tmp_path).mkdir(parents=True)
    (root_of(tmp_path) / "pumpkin").write_bytes(FAKE_BINARY + b"?")
    with pytest.raises(ProvisionError, match="not a recorded Installation"):
        installed(ADAPTER, TARGET, tmp_path)


def test_nothing_installed_is_none(tmp_path: Path) -> None:
    assert installed(ADAPTER, TARGET, tmp_path) is None


def test_another_installed_build_is_never_replaced_silently(tmp_path: Path) -> None:
    install_entry(ADAPTER, TARGET, tmp_path, ENTRY, FakeGitHub())
    other = dataclasses.replace(ENTRY, version="nightly-other")
    with pytest.raises(ProvisionError) as raised:
        install_entry(ADAPTER, TARGET, tmp_path, other, FakeGitHub())
    assert "already installed" in str(raised.value)
    assert (
        f"delete {root_of(tmp_path)} and run `mscts adapter install pumpkin --version "
        "nightly-other`"
    ) in str(raised.value)


def write(path: Path, body: bytes) -> Path:
    path.write_bytes(body)
    return path


def test_install_from_a_file_that_is_an_entry_records_both(tmp_path: Path) -> None:
    supplied = write(tmp_path / "pumpkin-X64-Linux", FAKE_BINARY)
    done = install_from(ADAPTER, TARGET, tmp_path / "cache", supplied, REGISTRY)
    source = recorded(tmp_path / "cache")
    assert (source["entry"], source["from_path"], source["sha256"], source["url"]) == (
        "pumpkin nightly-test",
        str(supplied),
        ENTRY.sha256,
        None,
    )
    assert done.changed
    assert done.message == (
        f"installed {supplied} (sha256 {ENTRY.sha256}; the Registry entry pumpkin "
        f"nightly-test) into {root_of(tmp_path / 'cache')}"
    )


def test_install_from_a_file_that_is_no_entry_never_claims_one(tmp_path: Path) -> None:
    body = b"\x7fELF my own build"
    supplied = write(tmp_path / "pumpkin", body)
    done = install_from(ADAPTER, TARGET, tmp_path / "cache", supplied, REGISTRY)
    source = recorded(tmp_path / "cache")
    assert (source["entry"], source["sha256"]) == (None, hashlib.sha256(body).hexdigest())
    assert "no Registry entry" in done.message
    assert (root_of(tmp_path / "cache") / "pumpkin").read_bytes() == body


def test_install_from_the_installed_file_again_is_a_no_op_that_says_so(tmp_path: Path) -> None:
    supplied = write(tmp_path / "pumpkin", FAKE_BINARY)
    install_from(ADAPTER, TARGET, tmp_path / "cache", supplied, REGISTRY)
    done = install_from(ADAPTER, TARGET, tmp_path / "cache", supplied, REGISTRY)
    assert not done.changed
    assert done.message.endswith(f"with sha256 {ENTRY.sha256}: nothing to do")


def test_install_from_another_file_over_an_installation_names_the_fix(tmp_path: Path) -> None:
    install_from(ADAPTER, TARGET, tmp_path / "cache", write(tmp_path / "a", FAKE_BINARY), REGISTRY)
    other = write(tmp_path / "b", b"\x7fELF another")
    with pytest.raises(ProvisionError) as raised:
        install_from(ADAPTER, TARGET, tmp_path / "cache", other, REGISTRY)
    assert f"`mscts adapter install pumpkin --from {other}`" in str(raised.value)


def test_install_from_a_missing_file_says_so(tmp_path: Path) -> None:
    with pytest.raises(ProvisionError, match="cannot read"):
        install_from(ADAPTER, TARGET, tmp_path, tmp_path / "nothing", REGISTRY)


def test_install_from_a_file_that_is_not_an_elf_executable_is_refused(tmp_path: Path) -> None:
    supplied = write(tmp_path / "page.html", b"<!DOCTYPE html>")
    with pytest.raises(ProvisionError, match="ELF"):
        install_from(ADAPTER, TARGET, tmp_path / "cache", supplied, REGISTRY)
    assert not root_of(tmp_path / "cache").exists()


def test_the_root_is_absolute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    done = install_entry(ADAPTER, TARGET, Path("cache"), ENTRY, FakeGitHub())
    assert done.installation.root == tmp_path / "cache/pumpkin/26.3"
