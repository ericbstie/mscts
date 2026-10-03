import hashlib
import json

import pytest

from mscts.adapters.base import Build, Download, ProvisionError, Release
from mscts.adapters.vanilla import MANIFEST_URL, VanillaAdapter
from mscts.target import TARGET

VERSION_URL = "https://piston-meta.example/v1/packages/abc/26.3.json"
JAR_URL = "https://piston-data.example/v1/objects/def/server.jar"
JAR_SHA1 = "33680f5f2ac32864d6d7cf5e56a705fdb3e05f4c"
VERSION_JSON = json.dumps(
    {"id": "26.3", "downloads": {"server": {"sha1": JAR_SHA1, "size": 62294556, "url": JAR_URL}}}
).encode()


def manifest() -> bytes:
    """Mojang's version manifest, listing 26.3 by the sha1 of VERSION_JSON."""
    sha1 = hashlib.sha1(VERSION_JSON, usedforsecurity=False).hexdigest()
    versions = [
        {"id": "26.4-snapshot-2", "type": "snapshot", "url": "https://x.example/a.json"},
        {"id": "26.3", "type": "release", "url": VERSION_URL, "sha1": sha1},
    ]
    return json.dumps({"latest": {"release": "26.3"}, "versions": versions}).encode()


class FakeMojang:
    """A fetch that serves the manifest and 26.3's version JSON, recording every URL asked."""

    def __init__(self, version_json: bytes = VERSION_JSON) -> None:
        self.bodies = {MANIFEST_URL: manifest(), VERSION_URL: version_json}
        self.fetched: list[str] = []

    def __call__(self, url: str) -> Download:
        self.fetched.append(url)
        return Download(url=url, body=self.bodies[url])


RELEASE = Release(build=Build(version="26.3"), url=JAR_URL, sha1=JAR_SHA1, size=62294556)


@pytest.mark.parametrize("version", [None, "26.3"])
def test_the_target_s_release_is_the_server_jar_mojang_lists_for_it(version: str | None) -> None:
    mojang = FakeMojang()
    assert VanillaAdapter().release(TARGET, version, mojang) == RELEASE
    assert mojang.fetched == [MANIFEST_URL, VERSION_URL]


@pytest.mark.parametrize("version", ["26.4", "26.2", "1.21.8"])
def test_another_version_is_not_supported_and_nothing_is_fetched(version: str) -> None:
    mojang = FakeMojang()
    with pytest.raises(ProvisionError) as raised:
        VanillaAdapter().release(TARGET, version, mojang)
    assert (
        str(raised.value) == f"vanilla@{version} is not supported: this mscts tests Minecraft 26.3."
    )
    assert mojang.fetched == []


def test_a_version_json_that_is_not_the_one_the_manifest_lists_is_refused() -> None:
    with pytest.raises(ProvisionError, match="is not the version JSON"):
        VanillaAdapter().release(TARGET, None, FakeMojang(VERSION_JSON + b" "))


def test_a_manifest_without_the_target_is_an_error() -> None:
    mojang = FakeMojang()
    mojang.bodies[MANIFEST_URL] = json.dumps({"versions": []}).encode()
    with pytest.raises(ProvisionError, match=r"lists no 26\.3"):
        VanillaAdapter().release(TARGET, None, mojang)
