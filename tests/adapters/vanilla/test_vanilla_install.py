import hashlib
import json
from pathlib import Path

import pytest
from support.vanilla import JAR_URL, VERSION_URL, FakeMojang, fake_jar, manifest, sha1

from mscts.adapters.base import Build, ProvisionError, Source, UnsupportedError
from mscts.adapters.fetch import ChecksumError, HttpsNet
from mscts.adapters.vanilla import MANIFEST_URL, VanillaAdapter
from mscts.install import install_release, installed
from mscts.target import TARGET

PUBLISHED = fake_jar()


@pytest.mark.parametrize("version", [None, "26.3"])
def test_install_puts_the_jar_mojang_lists_for_the_target_into_the_file(
    tmp_path: Path, version: str | None
) -> None:
    mojang = FakeMojang()
    into = tmp_path / "server.jar"
    assert VanillaAdapter().install(TARGET, version, into, HttpsNet(mojang)) == Build("26.3")
    assert into.read_bytes() == PUBLISHED
    assert mojang.fetched == [MANIFEST_URL, VERSION_URL, JAR_URL]


@pytest.mark.parametrize("version", ["26.4", "26.2", "1.21.8"])
def test_install_of_another_version_is_not_supported_and_fetches_nothing(
    tmp_path: Path, version: str
) -> None:
    mojang = FakeMojang()
    with pytest.raises(UnsupportedError) as raised:
        VanillaAdapter().install(TARGET, version, tmp_path / "server.jar", HttpsNet(mojang))
    assert (
        str(raised.value) == f"vanilla@{version} is not supported: this mscts tests Minecraft 26.3."
    )
    assert mojang.fetched == []
    assert list(tmp_path.iterdir()) == []


def test_install_refuses_a_version_json_that_is_not_the_one_the_manifest_lists(
    tmp_path: Path,
) -> None:
    mojang = FakeMojang()
    mojang.bodies[VERSION_URL] += b" "
    with pytest.raises(ProvisionError) as raised:
        VanillaAdapter().install(TARGET, None, tmp_path / "server.jar", HttpsNet(mojang))
    assert str(raised.value).startswith(f"{VERSION_URL} is not what its publisher lists: ")
    assert list(tmp_path.iterdir()) == []


def test_install_from_a_manifest_without_the_target_says_so(tmp_path: Path) -> None:
    mojang = FakeMojang()
    mojang.bodies[MANIFEST_URL] = json.dumps({"versions": []}).encode()
    with pytest.raises(ProvisionError) as raised:
        VanillaAdapter().install(TARGET, None, tmp_path / "server.jar", HttpsNet(mojang))
    assert str(raised.value) == f"{MANIFEST_URL} lists no 26.3"


def test_install_refuses_a_jar_that_is_not_the_one_mojang_lists(tmp_path: Path) -> None:
    mojang = FakeMojang(PUBLISHED + b"\0", jar=PUBLISHED)
    with pytest.raises(ChecksumError) as raised:
        VanillaAdapter().install(TARGET, None, tmp_path / "server.jar", HttpsNet(mojang))
    assert str(raised.value).startswith(f"{JAR_URL} is not the file its publisher lists: ")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("version", [None, "26.3"])
def test_install_release_installs_the_published_jar_into_the_cache(
    tmp_path: Path, version: str | None
) -> None:
    mojang = FakeMojang()
    done = install_release(VanillaAdapter(), TARGET, tmp_path, version, mojang)
    installation = done.installation
    assert (installation.adapter, installation.target) == ("vanilla", TARGET)
    assert installation.root == tmp_path / "vanilla/26.3"
    assert installation.source is not None
    assert installation.source.build == Build(version="26.3")
    assert (installation.root / "server.jar").read_bytes() == PUBLISHED
    assert mojang.fetched == [MANIFEST_URL, VERSION_URL, JAR_URL]
    assert done.message == f"installed vanilla 26.3 from {JAR_URL} into {installation.root}"


@pytest.mark.parametrize(
    "served",
    [
        # Same size, different bytes from those the published sha1 names.
        PUBLISHED[:-1] + bytes([PUBLISHED[-1] ^ 0xFF]),
        PUBLISHED + b"\0",
    ],
    ids=["same-size-other-bytes", "one-byte-longer"],
)
def test_install_release_rejects_a_download_that_is_not_the_published_jar(
    tmp_path: Path, served: bytes
) -> None:
    assert served != PUBLISHED
    with pytest.raises(ProvisionError) as raised:
        install_release(VanillaAdapter(), TARGET, tmp_path, None, FakeMojang(served, jar=PUBLISHED))
    assert str(raised.value) == (
        f"{JAR_URL} is not the file its publisher lists: sha1 {sha1(served)}, {len(served)} "
        f"bytes, where its publisher lists sha1 {sha1(PUBLISHED)}, {len(PUBLISHED)} bytes.\n"
        "To run that file anyway, save it and run `mscts adapter install vanilla --from <file>`"
    )
    assert list((tmp_path / "vanilla").iterdir()) == []  # nothing installed, nothing staged


def test_another_version_is_not_supported_even_with_26_3_installed(tmp_path: Path) -> None:
    install_release(VanillaAdapter(), TARGET, tmp_path, None, FakeMojang())
    with pytest.raises(ProvisionError) as raised:
        install_release(VanillaAdapter(), TARGET, tmp_path, "26.4", FakeMojang())
    assert str(raised.value) == "vanilla@26.4 is not supported: this mscts tests Minecraft 26.3."


@pytest.mark.parametrize(
    ("version", "wanted"), [(None, "vanilla's latest build"), ("26.3", "vanilla@26.3")]
)
def test_a_garbled_manifest_names_the_adapter_and_the_from_command(
    tmp_path: Path, version: str | None, wanted: str
) -> None:
    mojang = FakeMojang()
    mojang.bodies[MANIFEST_URL] = b"<html>The proxy says no</html>"
    with pytest.raises(ProvisionError) as raised:
        install_release(VanillaAdapter(), TARGET, tmp_path, version, mojang)
    assert str(raised.value) == (
        f"{wanted} could not be found: JSONDecodeError: "
        "Expecting value: line 1 column 1 (char 0)\n"
        "Download the build another way, then run "
        "`mscts adapter install vanilla --from <file>`"
    )
    assert list((tmp_path / "vanilla").iterdir()) == []  # nothing installed, nothing staged


def test_install_release_rejects_a_download_of_another_size_than_listed(tmp_path: Path) -> None:
    mojang = FakeMojang()
    listed = json.loads(mojang.bodies[VERSION_URL])
    listed["downloads"]["server"]["size"] += 1
    mojang.bodies[VERSION_URL] = json.dumps(listed).encode()
    mojang.bodies[MANIFEST_URL] = manifest(mojang.bodies[VERSION_URL])
    with pytest.raises(ProvisionError) as raised:
        install_release(VanillaAdapter(), TARGET, tmp_path, None, mojang)
    assert str(raised.value).startswith(f"{JAR_URL} is not the file its publisher lists: ")
    assert list((tmp_path / "vanilla").iterdir()) == []


def test_check_refuses_a_file_that_is_no_jar(tmp_path: Path) -> None:
    (tmp_path / "server.jar").write_bytes(b"PK not a zip")
    with pytest.raises(ProvisionError, match="not a vanilla"):
        VanillaAdapter().check(tmp_path / "server.jar", TARGET)


def test_check_refuses_a_jar_for_another_protocol(tmp_path: Path) -> None:
    (tmp_path / "server.jar").write_bytes(fake_jar(protocol_version=778))
    said = (
        f"{tmp_path / 'server.jar'} is not supported: it is vanilla 26.3 speaking protocol "
        "778 (not 777), and this mscts tests Minecraft 26.3."
    )
    with pytest.raises(UnsupportedError) as raised:
        VanillaAdapter().check(tmp_path / "server.jar", TARGET)
    assert str(raised.value) == said


def test_check_names_the_version_a_jar_says_it_is(tmp_path: Path) -> None:
    (tmp_path / "server.jar").write_bytes(fake_jar())
    assert VanillaAdapter().check(tmp_path / "server.jar", TARGET) == Build(version="26.3")


def test_check_refuses_a_jar_for_another_minecraft_version(tmp_path: Path) -> None:
    (tmp_path / "server.jar").write_bytes(fake_jar(version="26.4"))
    said = (
        f"{tmp_path / 'server.jar'} is not supported: it is vanilla 26.4, "
        "and this mscts tests Minecraft 26.3."
    )
    with pytest.raises(ProvisionError) as raised:
        VanillaAdapter().check(tmp_path / "server.jar", TARGET)
    assert str(raised.value) == said


def test_a_download_recorded_before_builds_were_reads_its_label(tmp_path: Path) -> None:
    root = tmp_path / "vanilla/26.3"
    root.mkdir(parents=True)
    (root / "server.jar").write_bytes(PUBLISHED)
    sha256 = hashlib.sha256(PUBLISHED).hexdigest()
    legacy = {"sha256": sha256, "size": len(PUBLISHED), "entry": "vanilla 26.3", "url": JAR_URL}
    (root / "SOURCE.json").write_text(json.dumps(legacy))
    found = installed(VanillaAdapter(), TARGET, tmp_path)
    assert found is not None
    assert found.source == Source(sha256=sha256, size=len(PUBLISHED), version="26.3", url=JAR_URL)
