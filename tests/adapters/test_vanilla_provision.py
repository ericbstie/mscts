import dataclasses
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from mscts.adapters.base import Adapter, Installation, ProvisionError
from mscts.adapters.vanilla import VanillaAdapter, https_get
from mscts.target import TARGET

MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
VERSION_URL = "https://piston-meta.example/v1/packages/abc/26.3.json"
JAR_URL = "https://piston-data.example/v1/objects/def/server.jar"


def sha1(data: bytes) -> str:
    return hashlib.sha1(data, usedforsecurity=False).hexdigest()


def fake_jar(protocol_version: int = 777) -> bytes:
    """A tiny stand-in for the server jar: a zip whose version.json names the protocol."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as jar:
        version = {"id": "26.3", "protocol_version": protocol_version, "java_version": 25}
        jar.writestr("version.json", json.dumps(version))
        jar.writestr("net/minecraft/bundler/Main.class", b"\xca\xfe\xba\xbe")
    return buffer.getvalue()


def serve(
    *, jar: bytes | None = None, java_major: int = 25, size: int | None = None
) -> dict[str, bytes]:
    """The manifest, version JSON and jar, shaped like Mojang's, keyed by URL."""
    jar = fake_jar() if jar is None else jar
    version = json.dumps(
        {
            "id": "26.3",
            "javaVersion": {"component": "java-runtime-epsilon", "majorVersion": java_major},
            "downloads": {
                "server": {
                    "sha1": sha1(jar),
                    "size": len(jar) if size is None else size,
                    "url": JAR_URL,
                }
            },
        }
    ).encode()
    manifest = json.dumps(
        {
            "latest": {"release": "26.3", "snapshot": "26.4-snapshot-1"},
            "versions": [
                {
                    "id": "26.4-snapshot-1",
                    "type": "snapshot",
                    "url": "https://piston-meta.example/v1/packages/0/26.4-snapshot-1.json",
                    "sha1": "0" * 40,
                },
                {"id": "26.3", "type": "release", "url": VERSION_URL, "sha1": sha1(version)},
            ],
        }
    ).encode()
    return {MANIFEST_URL: manifest, VERSION_URL: version, JAR_URL: jar}


class FakeMojang:
    """A fetch that serves canned documents and records every URL it was asked for."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.fetched: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.fetched.append(url)
        return self.files[url]


@pytest.mark.parametrize(
    "url", ["file:///etc/hostname", "http://piston-meta.mojang.com/", "ftp://example.com/x"]
)
def test_https_get_refuses_other_schemes_before_connecting(url: str) -> None:
    with pytest.raises(ProvisionError, match="HTTPS"):
        https_get(url)


def test_provision_downloads_the_jar_into_the_cache(tmp_path: Path) -> None:
    mojang = FakeMojang(serve())
    adapter: Adapter = VanillaAdapter(fetch=mojang)
    installation = adapter.provision(TARGET, tmp_path)
    assert installation == Installation(
        adapter="vanilla", target=TARGET, root=tmp_path / "vanilla/26.3"
    )
    assert (installation.root / "server.jar").read_bytes() == mojang.files[JAR_URL]
    assert mojang.fetched == [MANIFEST_URL, VERSION_URL, JAR_URL]


def test_provision_reuses_a_cached_jar_whose_sha1_matches(tmp_path: Path) -> None:
    files = serve()
    VanillaAdapter(fetch=FakeMojang(files)).provision(TARGET, tmp_path)
    again = FakeMojang(files)
    VanillaAdapter(fetch=again).provision(TARGET, tmp_path)
    assert again.fetched == [MANIFEST_URL, VERSION_URL]


def test_provision_replaces_a_cached_jar_whose_sha1_mismatches(tmp_path: Path) -> None:
    root = tmp_path / "vanilla/26.3"
    root.mkdir(parents=True)
    (root / "server.jar").write_bytes(b"a truncated download")
    mojang = FakeMojang(serve())
    VanillaAdapter(fetch=mojang).provision(TARGET, tmp_path)
    assert mojang.fetched == [MANIFEST_URL, VERSION_URL, JAR_URL]
    assert (root / "server.jar").read_bytes() == mojang.files[JAR_URL]
    assert [path.name for path in root.iterdir()] == ["server.jar"]


def test_provision_rejects_a_download_whose_sha1_differs(tmp_path: Path) -> None:
    files = serve()
    tampered = bytearray(files[JAR_URL])
    tampered[-1] ^= 0xFF  # same size, different bytes from those the published sha1 names
    files[JAR_URL] = bytes(tampered)
    with pytest.raises(ProvisionError, match="sha1"):
        VanillaAdapter(fetch=FakeMojang(files)).provision(TARGET, tmp_path)
    assert not (tmp_path / "vanilla/26.3/server.jar").exists()


def test_provision_rejects_a_download_whose_size_differs(tmp_path: Path) -> None:
    with pytest.raises(ProvisionError, match="size"):
        VanillaAdapter(fetch=FakeMojang(serve(size=12))).provision(TARGET, tmp_path)
    assert not (tmp_path / "vanilla/26.3/server.jar").exists()


def test_provision_rejects_a_version_missing_from_the_manifest(tmp_path: Path) -> None:
    target = dataclasses.replace(TARGET, minecraft_version="99.9")
    with pytest.raises(ProvisionError, match=r"99\.9 is not in the version manifest"):
        VanillaAdapter(fetch=FakeMojang(serve())).provision(target, tmp_path)


def test_provision_rejects_a_version_json_whose_sha1_differs(tmp_path: Path) -> None:
    files = serve()
    files[VERSION_URL] += b"\n"  # still valid JSON, but not the published bytes
    mojang = FakeMojang(files)
    with pytest.raises(ProvisionError, match="sha1"):
        VanillaAdapter(fetch=mojang).provision(TARGET, tmp_path)
    assert JAR_URL not in mojang.fetched


def test_provision_rejects_a_version_that_needs_another_java(tmp_path: Path) -> None:
    mojang = FakeMojang(serve(java_major=21))
    with pytest.raises(ProvisionError, match="Java 21"):
        VanillaAdapter(fetch=mojang).provision(TARGET, tmp_path)
    assert JAR_URL not in mojang.fetched


def test_provision_rejects_a_jar_that_speaks_another_protocol(tmp_path: Path) -> None:
    files = serve(jar=fake_jar(protocol_version=778))
    with pytest.raises(ProvisionError, match="protocol 778"):
        VanillaAdapter(fetch=FakeMojang(files)).provision(TARGET, tmp_path)


def test_installation_root_is_absolute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    installation = VanillaAdapter(fetch=FakeMojang(serve())).provision(TARGET, Path("cache"))
    assert installation.root == tmp_path / "cache/vanilla/26.3"
