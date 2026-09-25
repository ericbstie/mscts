import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from mscts.adapters.base import Installation
from mscts.adapters.vanilla import MANIFEST_URL, VanillaAdapter, https_get
from mscts.target import TARGET

pytestmark = pytest.mark.reference

# What Mojang's manifest publishes for the 26.3 server jar (checked 2026-09-25).
SERVER_JAR_SHA1 = "33680f5f2ac32864d6d7cf5e56a705fdb3e05f4c"
SERVER_JAR_SIZE = 62294556


def test_provision_fetches_the_published_26_3_jar(cache_dir: Path) -> None:
    installation = VanillaAdapter().provision(TARGET, cache_dir)
    assert installation == Installation(
        adapter="vanilla", target=TARGET, root=cache_dir / "vanilla/26.3"
    )
    jar = (installation.root / "server.jar").read_bytes()
    assert (len(jar), hashlib.sha1(jar, usedforsecurity=False).hexdigest()) == (
        SERVER_JAR_SIZE,
        SERVER_JAR_SHA1,
    )
    with zipfile.ZipFile(installation.root / "server.jar") as archive:
        version = json.loads(archive.read("version.json"))
    assert (version["id"], version["protocol_version"], version["java_version"]) == (
        TARGET.minecraft_version,
        TARGET.protocol_version,
        TARGET.java_major,
    )


def test_provision_does_not_download_a_cached_jar_again(cache_dir: Path) -> None:
    jar = VanillaAdapter().provision(TARGET, cache_dir).root / "server.jar"
    before = jar.stat()
    fetched: list[str] = []

    def recording_get(url: str) -> bytes:
        fetched.append(url)
        return https_get(url)

    VanillaAdapter(fetch=recording_get).provision(TARGET, cache_dir)
    assert len(fetched) == 2  # the manifest and the version JSON; not the jar
    assert fetched[0] == MANIFEST_URL
    after = jar.stat()
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)
