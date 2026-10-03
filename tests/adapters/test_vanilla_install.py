import json
from pathlib import Path

import pytest
from support.vanilla import JAR_URL, VERSION_URL, FakeMojang, fake_jar, manifest

from mscts.adapters.base import Build, ProvisionError
from mscts.adapters.vanilla import MANIFEST_URL, VanillaAdapter
from mscts.install import install_release
from mscts.target import TARGET

PUBLISHED = fake_jar()


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
    with pytest.raises(ProvisionError, match=r"is not vanilla 26\.3"):
        install_release(VanillaAdapter(), TARGET, tmp_path, None, FakeMojang(served, jar=PUBLISHED))
    assert not (tmp_path / "vanilla/26.3").exists()


def test_install_release_rejects_a_download_of_another_size_than_listed(tmp_path: Path) -> None:
    mojang = FakeMojang()
    listed = json.loads(mojang.bodies[VERSION_URL])
    listed["downloads"]["server"]["size"] += 1
    mojang.bodies[VERSION_URL] = json.dumps(listed).encode()
    mojang.bodies[MANIFEST_URL] = manifest(mojang.bodies[VERSION_URL])
    with pytest.raises(ProvisionError, match=r"is not vanilla 26\.3"):
        install_release(VanillaAdapter(), TARGET, tmp_path, None, mojang)
    assert not (tmp_path / "vanilla/26.3").exists()


@pytest.mark.parametrize(
    ("jar", "error"),
    [(fake_jar(protocol_version=778), "speaks protocol 778"), (b"PK not a zip", "not a vanilla")],
    ids=["protocol-778", "not-a-zip"],
)
def test_check_refuses_a_jar_that_is_not_a_server_for_the_target(
    tmp_path: Path, jar: bytes, error: str
) -> None:
    (tmp_path / "server.jar").write_bytes(jar)
    with pytest.raises(ProvisionError, match=error):
        VanillaAdapter().check(tmp_path / "server.jar", TARGET)


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
