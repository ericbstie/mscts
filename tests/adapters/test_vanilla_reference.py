import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from mscts.adapters.base import Installation
from mscts.adapters.fetch import Download, https_get
from mscts.adapters.vanilla import VanillaAdapter
from mscts.registry import official
from mscts.spec import ServerSpec
from mscts.target import TARGET

# Any host address of 127.0.0.0/8 will do: prepare only writes it into the config.
HOST = "127.1.2.3"

pytestmark = pytest.mark.reference

MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
# What Mojang's manifest publishes for the 26.3 server jar (checked 2026-09-25).
SERVER_JAR_SHA1 = "33680f5f2ac32864d6d7cf5e56a705fdb3e05f4c"
SERVER_JAR_SIZE = 62294556


def test_the_registry_pins_the_jar_mojangs_manifest_publishes() -> None:
    manifest = json.loads(https_get(MANIFEST_URL).body)
    (listed,) = [v for v in manifest["versions"] if v["id"] == TARGET.minecraft_version]
    document = https_get(listed["url"]).body
    assert hashlib.sha1(document, usedforsecurity=False).hexdigest() == listed["sha1"]
    version = json.loads(document)
    assert version["javaVersion"]["majorVersion"] == TARGET.java_major
    server = version["downloads"]["server"]
    entry = official().resolve("vanilla", TARGET)
    assert (entry.url, entry.sha1, entry.size) == (server["url"], server["sha1"], server["size"])


def test_provision_fetches_the_published_26_3_jar(cache_dir: Path) -> None:
    installation = VanillaAdapter().provision(TARGET, cache_dir)
    assert (installation.adapter, installation.target, installation.root) == (
        "vanilla",
        TARGET,
        cache_dir / "vanilla/26.3",
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

    def recording_get(url: str) -> Download:
        fetched.append(url)
        return https_get(url)

    VanillaAdapter(fetch=recording_get).provision(TARGET, cache_dir)
    assert fetched == []
    after = jar.stat()
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)


def test_prepare_launches_the_targets_java_as_the_jvm_itself_reports(tmp_path: Path) -> None:
    # prepare trusts the runtime image's release file; here the named JVM confirms it.
    installation = Installation(adapter="vanilla", target=TARGET, root=tmp_path / "cache")
    plan = VanillaAdapter().prepare(
        installation, ServerSpec(host=HOST, port=25599), tmp_path / "work"
    )
    shown = subprocess.run(
        [plan.argv[0], "-XshowSettings:properties", "-version"],
        env=dict(plan.env),
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    lines = [line.partition(" = ") for line in shown.stderr.splitlines() if " = " in line]
    settings = {key.strip(): value.strip() for key, _, value in lines}
    assert settings["java.specification.version"] == str(TARGET.java_major)
    assert Path(settings["java.home"]) == Path(plan.argv[0]).parent.parent
