import datetime
import hashlib
import http.client
import json
from pathlib import Path

import pytest
from support.pumpkin import ASSET_URL, COMMIT, FakeGitHub, fake_pumpkin, refs

from mscts.adapters.base import (
    Build,
    Download,
    Installation,
    ProvisionError,
    Source,
    UnavailableError,
)
from mscts.adapters.pumpkin import NIGHTLY_URL, TAGS_URL, PumpkinAdapter
from mscts.install import install_from, install_release, installed
from mscts.target import TARGET

NIGHTLY = fake_pumpkin()
SHA256 = hashlib.sha256(NIGHTLY).hexdigest()
ADAPTER = PumpkinAdapter()
OTHER = "8f3c2a1d00000000000000000000000000000000"


def root_of(cache: Path) -> Path:
    return cache / "pumpkin/26.3"


def recorded(cache: Path) -> dict[str, object]:
    source: object = json.loads((root_of(cache) / "SOURCE.json").read_text(encoding="utf-8"))
    assert isinstance(source, dict)
    return {str(key): value for key, value in source.items()}


def test_install_release_downloads_the_latest_build_and_records_it(tmp_path: Path) -> None:
    github = FakeGitHub()
    before = datetime.datetime.now(datetime.UTC).replace(microsecond=0)
    done = install_release(ADAPTER, TARGET, tmp_path, None, github)
    assert github.fetched == [TAGS_URL, NIGHTLY_URL]
    assert done.changed
    assert done.message == (
        f"installed pumpkin nightly 4426d11 from {NIGHTLY_URL} into {root_of(tmp_path)}"
    )
    source = recorded(tmp_path)
    installed_at = datetime.datetime.fromisoformat(str(source.pop("installed_at")))
    assert before <= installed_at <= datetime.datetime.now(datetime.UTC)
    assert source == {
        "sha256": SHA256,
        "size": len(NIGHTLY),
        "version": "nightly",
        "commit": COMMIT,
        "url": NIGHTLY_URL,
        "final_url": ASSET_URL,
        "from_path": None,
    }
    assert done.installation == Installation(
        adapter="pumpkin",
        target=TARGET,
        root=root_of(tmp_path),
        source=Source(
            sha256=SHA256,
            size=len(NIGHTLY),
            version="nightly",
            commit=COMMIT,
            url=NIGHTLY_URL,
            final_url=ASSET_URL,
            installed_at=installed_at.isoformat(),
        ),
    )
    binary = root_of(tmp_path) / "pumpkin"
    assert binary.read_bytes() == NIGHTLY
    assert binary.stat().st_mode & 0o777 == 0o755
    assert sorted(p.name for p in root_of(tmp_path).iterdir()) == ["SOURCE.json", "pumpkin"]
    assert sorted(p.name for p in (tmp_path / "pumpkin").iterdir()) == ["26.3"]


def test_a_source_names_its_build() -> None:
    source = Source(sha256=SHA256, size=1, version="nightly", commit=COMMIT)
    assert source.build == Build(version="nightly", commit=COMMIT)
    assert Source(sha256=SHA256, size=1).build is None


@pytest.mark.parametrize("version", [None, COMMIT[:7], "nightly"])
def test_installing_the_installed_build_again_is_a_no_op_that_says_so(
    tmp_path: Path, version: str | None
) -> None:
    install_release(ADAPTER, TARGET, tmp_path, None, FakeGitHub())
    binary = root_of(tmp_path) / "pumpkin"
    before = binary.stat()
    again = FakeGitHub(tags=refs(OTHER))  # a newer nightly is out: it is never fetched
    done = install_release(ADAPTER, TARGET, tmp_path, version, again)
    assert again.fetched == []
    assert not done.changed
    root = root_of(tmp_path)
    assert done.message == (
        f"pumpkin nightly 4426d11 is already installed at {root} (sha256 {SHA256}): "
        f"nothing to do. To check for a newer build, delete {root} and install again."
    )
    after = binary.stat()
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)


def test_another_installed_build_is_never_replaced_silently(tmp_path: Path) -> None:
    older = fake_pumpkin(commit=OTHER)
    install_release(ADAPTER, TARGET, tmp_path, None, FakeGitHub(older, tags=refs(OTHER)))
    github = FakeGitHub()  # the nightly has moved on to COMMIT
    with pytest.raises(ProvisionError) as raised:
        install_release(ADAPTER, TARGET, tmp_path, "4426d11", github)
    sha256 = hashlib.sha256(older).hexdigest()
    assert str(raised.value) == (
        f"pumpkin 26.3 is already installed at {root_of(tmp_path)}: pumpkin nightly 8f3c2a1, "
        f"from {NIGHTLY_URL} (sha256 {sha256}). To install pumpkin@4426d11 instead, delete "
        f"{root_of(tmp_path)} and run `mscts adapter install pumpkin@4426d11`"
    )
    assert (root_of(tmp_path) / "pumpkin").read_bytes() == older


# A commit is named by 7 or more of its first characters: 4426 names no build.
@pytest.mark.parametrize(
    ("version", "said", "fetched"),
    [
        ("8f3c2a1", "is not available", [TAGS_URL, NIGHTLY_URL]),  # only the file can say
        (COMMIT[:4], "is too short", []),
    ],
)
def test_a_build_that_cannot_be_installed_says_so_over_an_installed_one(
    tmp_path: Path, version: str, said: str, fetched: list[str]
) -> None:
    install_release(ADAPTER, TARGET, tmp_path, None, FakeGitHub())
    github = FakeGitHub()
    with pytest.raises(ProvisionError, match=rf"^pumpkin@{version} {said}"):
        install_release(ADAPTER, TARGET, tmp_path, version, github)
    assert github.fetched == fetched


def test_the_file_s_own_commit_is_installed_and_reported_whatever_the_tag_says(
    tmp_path: Path,
) -> None:
    # The tag moves before the new binary is uploaded: for a few minutes they disagree. The
    # tag only finds the file; what was installed is what the file says it is.
    done = install_release(ADAPTER, TARGET, tmp_path, None, FakeGitHub(tags=refs(OTHER)))
    assert done.message == (
        f"installed pumpkin nightly 4426d11 from {NIGHTLY_URL} into {root_of(tmp_path)}"
    )
    assert (recorded(tmp_path)["version"], recorded(tmp_path)["commit"]) == ("nightly", COMMIT)
    assert done.installation.source is not None
    assert done.installation.source.build == Build(version="nightly", commit=COMMIT)


def test_the_file_s_commit_named_while_the_tag_has_moved_on_is_installed(
    tmp_path: Path,
) -> None:
    done = install_release(ADAPTER, TARGET, tmp_path, COMMIT[:7], FakeGitHub(tags=refs(OTHER)))
    assert done.installation.source is not None
    assert done.installation.source.build == Build(version="nightly", commit=COMMIT)


def test_a_named_commit_the_file_is_not_is_unavailable(tmp_path: Path) -> None:
    with pytest.raises(UnavailableError) as raised:
        install_release(ADAPTER, TARGET, tmp_path, OTHER[:7], FakeGitHub(tags=refs(OTHER)))
    assert str(raised.value).startswith(
        "pumpkin@8f3c2a1 is not available for download. The latest is pumpkin nightly 4426d11."
    )
    assert list((tmp_path / "pumpkin").iterdir()) == []  # no staging directory left


def test_a_file_that_names_no_commit_is_refused_when_its_label_names_one(tmp_path: Path) -> None:
    github = FakeGitHub(binary=fake_pumpkin(commit="unknown"))
    with pytest.raises(ProvisionError) as raised:
        install_release(ADAPTER, TARGET, tmp_path, None, github)
    assert str(raised.value).startswith(
        f"{NIGHTLY_URL} names no commit, so which pumpkin nightly it is cannot be told."
    )
    assert "--from <file>" in str(raised.value)
    assert list((tmp_path / "pumpkin").iterdir()) == []


def test_a_download_that_is_not_an_elf_executable_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ProvisionError, match="ELF"):
        install_release(ADAPTER, TARGET, tmp_path, None, FakeGitHub(b"<!DOCTYPE html>"))
    assert not root_of(tmp_path).exists()
    assert list((tmp_path / "pumpkin").iterdir()) == []  # no staging directory left


@pytest.mark.parametrize("failing", [TAGS_URL, NIGHTLY_URL], ids=["lookup", "download"])
def test_a_failed_fetch_leaves_nothing_behind_and_names_the_fix(
    tmp_path: Path, failing: str
) -> None:
    github = FakeGitHub()

    def flaky(url: str) -> Download:
        if url == failing:
            msg = f"connection reset fetching {url}"
            raise OSError(msg)
        return github(url)

    with pytest.raises(ProvisionError, match=r"connection reset(.|\n)*--from <file>"):
        install_release(ADAPTER, TARGET, tmp_path, None, flaky)
    assert not root_of(tmp_path).exists()


def test_a_download_cut_off_midway_names_the_fix(tmp_path: Path) -> None:
    github = FakeGitHub()

    def cut_off(url: str) -> Download:
        if url == NIGHTLY_URL:
            partial = b"partial"
            raise http.client.IncompleteRead(partial, 100)
        return github(url)

    with pytest.raises(ProvisionError, match=r"IncompleteRead(.|\n)*--from <file>"):
        install_release(ADAPTER, TARGET, tmp_path, None, cut_off)
    assert not root_of(tmp_path).exists()


def test_a_concurrent_install_that_finishes_first_wins(tmp_path: Path) -> None:
    github = FakeGitHub()

    def slower(url: str) -> Download:
        if url == NIGHTLY_URL:
            install_release(ADAPTER, TARGET, tmp_path, None, FakeGitHub())  # another session
        return github(url)

    done = install_release(ADAPTER, TARGET, tmp_path, None, slower)
    assert done.installation.root == root_of(tmp_path)
    assert sorted(p.name for p in (tmp_path / "pumpkin").iterdir()) == ["26.3"]


def test_a_concurrent_install_that_wins_is_the_one_reported(tmp_path: Path) -> None:
    theirs = write(tmp_path / "theirs", fake_pumpkin(tail=b"theirs"))
    github = FakeGitHub()

    def slower(url: str) -> Download:
        if url == NIGHTLY_URL:
            install_from(ADAPTER, TARGET, tmp_path / "cache", theirs)  # another session
        return github(url)

    done = install_release(ADAPTER, TARGET, tmp_path / "cache", None, slower)
    assert done.message == (
        f"installed {theirs} (pumpkin 0.2.0+26.3-26.51 4426d11, sha256 "
        f"{hashlib.sha256(theirs.read_bytes()).hexdigest()}) into {root_of(tmp_path / 'cache')}"
    )


def test_an_installation_whose_binary_changed_is_refused_naming_the_fix(tmp_path: Path) -> None:
    install_release(ADAPTER, TARGET, tmp_path, None, FakeGitHub())
    (root_of(tmp_path) / "pumpkin").write_bytes(NIGHTLY + b"!")
    github = FakeGitHub()
    with pytest.raises(ProvisionError) as raised:
        install_release(ADAPTER, TARGET, tmp_path, None, github)
    assert f"is not the recorded {SHA256}" in str(raised.value)
    assert f"delete {root_of(tmp_path)} and run `mscts adapter install pumpkin` again" in str(
        raised.value
    )
    assert github.fetched == []  # never silently replaced


def test_an_unrecorded_installation_is_refused_naming_the_fix(tmp_path: Path) -> None:
    root_of(tmp_path).mkdir(parents=True)
    (root_of(tmp_path) / "pumpkin").write_bytes(NIGHTLY)
    with pytest.raises(ProvisionError, match=r"not a recorded Installation.*delete"):
        installed(ADAPTER, TARGET, tmp_path)


def test_an_installation_recorded_before_builds_were_reads_its_build_from_the_binary(
    tmp_path: Path,
) -> None:
    root_of(tmp_path).mkdir(parents=True)
    (root_of(tmp_path) / "pumpkin").write_bytes(NIGHTLY)
    legacy = {"sha256": SHA256, "size": len(NIGHTLY), "entry": "pumpkin nightly-b8382a8a"}
    (root_of(tmp_path) / "SOURCE.json").write_text(json.dumps(legacy))
    found = installed(ADAPTER, TARGET, tmp_path)
    assert found is not None
    assert found.source == Source(
        sha256=SHA256, size=len(NIGHTLY), version="0.2.0+26.3-26.51", commit=COMMIT
    )
    assert json.loads((root_of(tmp_path) / "SOURCE.json").read_text()) == legacy  # unchanged


def test_nothing_installed_is_none(tmp_path: Path) -> None:
    assert installed(ADAPTER, TARGET, tmp_path) is None


def write(path: Path, body: bytes) -> Path:
    path.write_bytes(body)
    return path


def test_install_from_records_the_build_the_file_names_and_where_it_came_from(
    tmp_path: Path,
) -> None:
    supplied = write(tmp_path / "pumpkin-X64-Linux", NIGHTLY)
    done = install_from(ADAPTER, TARGET, tmp_path / "cache", supplied)
    source = recorded(tmp_path / "cache")
    assert (source["version"], source["commit"], source["from_path"], source["url"]) == (
        "0.2.0+26.3-26.51",
        COMMIT,
        str(supplied),
        None,
    )
    assert done.changed
    assert done.message == (
        f"installed {supplied} (pumpkin 0.2.0+26.3-26.51 4426d11, sha256 {SHA256}) "
        f"into {root_of(tmp_path / 'cache')}"
    )


def test_install_from_the_installed_file_again_is_a_no_op_that_says_so(tmp_path: Path) -> None:
    supplied = write(tmp_path / "pumpkin", NIGHTLY)
    install_from(ADAPTER, TARGET, tmp_path / "cache", supplied)
    done = install_from(ADAPTER, TARGET, tmp_path / "cache", supplied)
    assert not done.changed
    assert done.message.endswith(f"with sha256 {SHA256}: nothing to do")


def test_install_from_another_file_over_an_installation_names_the_fix(tmp_path: Path) -> None:
    install_from(ADAPTER, TARGET, tmp_path / "cache", write(tmp_path / "a", NIGHTLY))
    other = write(tmp_path / "b", fake_pumpkin(tail=b"another"))
    with pytest.raises(ProvisionError) as raised:
        install_from(ADAPTER, TARGET, tmp_path / "cache", other)
    assert f"`mscts adapter install pumpkin --from {other}`" in str(raised.value)


def test_install_from_a_missing_file_says_so(tmp_path: Path) -> None:
    with pytest.raises(ProvisionError, match="cannot read"):
        install_from(ADAPTER, TARGET, tmp_path, tmp_path / "nothing")


def test_install_from_a_build_for_another_minecraft_version_is_refused(tmp_path: Path) -> None:
    supplied = write(tmp_path / "pumpkin", fake_pumpkin(version="0.2.0+26.4-26.60"))
    with pytest.raises(ProvisionError) as raised:
        install_from(ADAPTER, TARGET, tmp_path / "cache", supplied)
    assert str(raised.value).startswith(f"{supplied} is not supported: "), raised.value
    assert not root_of(tmp_path / "cache").exists()


def test_install_from_an_unsupported_file_over_an_installation_says_so_first(
    tmp_path: Path,
) -> None:
    install_from(ADAPTER, TARGET, tmp_path / "cache", write(tmp_path / "a", NIGHTLY))
    supplied = write(tmp_path / "b", fake_pumpkin(version="0.2.0+26.4-26.60"))
    with pytest.raises(ProvisionError) as raised:
        install_from(ADAPTER, TARGET, tmp_path / "cache", supplied)
    assert str(raised.value).startswith(f"{supplied} is not supported: "), raised.value


def test_the_root_is_absolute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    done = install_release(ADAPTER, TARGET, Path("cache"), None, FakeGitHub())
    assert done.installation.root == tmp_path / "cache/pumpkin/26.3"


def test_pumpkin_at_nightly_installs_the_latest_nightly(tmp_path: Path) -> None:
    done = install_release(ADAPTER, TARGET, tmp_path, "nightly", FakeGitHub())
    assert done.message == (
        f"installed pumpkin nightly 4426d11 from {NIGHTLY_URL} into {root_of(tmp_path)}"
    )


@pytest.mark.parametrize(
    ("version", "asked"), [(None, "pumpkin's latest build"), ("4426d11", "pumpkin@4426d11")]
)
def test_a_nightly_for_another_minecraft_version_says_so_and_how_to_get_one(
    tmp_path: Path, version: str | None, asked: str
) -> None:
    github = FakeGitHub(binary=fake_pumpkin(version="0.3.0+26.4-27.1"))
    with pytest.raises(ProvisionError) as raised:
        install_release(ADAPTER, TARGET, tmp_path, version, github)
    assert str(raised.value) == (
        f"{asked} ({NIGHTLY_URL}) is not supported: it is Pumpkin 0.3.0+26.4-27.1, "
        "for Minecraft 26.4, and this mscts tests Minecraft 26.3.\n"
        "Build it yourself and install it with:\n"
        "  mscts adapter install pumpkin --from <file>"
    )
    assert list((tmp_path / "pumpkin").iterdir()) == []
