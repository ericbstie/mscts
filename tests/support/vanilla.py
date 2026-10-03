"""Stand-ins for vanilla server jars and for Mojang, which publishes them: never run."""

import hashlib
import io
import json
import zipfile

from mscts.adapters.base import Download
from mscts.adapters.vanilla import MANIFEST_URL

VERSION_URL = "https://piston-meta.example/v1/packages/abc/26.3.json"
JAR_URL = "https://piston-data.example/v1/objects/def/server.jar"
# A fixed date for zip entries: pytest-xdist workers collecting at different seconds must see
# the same parametrized tests.
ZIP_DATE = (2026, 1, 1, 0, 0, 0)


def fake_jar(protocol_version: int = 777, version: str = "26.3") -> bytes:
    """A tiny stand-in for the server jar: a zip whose version.json names its version."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as jar:
        about = {"id": version, "protocol_version": protocol_version, "java_version": 25}
        jar.writestr(zipfile.ZipInfo("version.json", ZIP_DATE), json.dumps(about))
        jar.writestr(
            zipfile.ZipInfo("net/minecraft/bundler/Main.class", ZIP_DATE), b"\xca\xfe\xba\xbe"
        )
    return buffer.getvalue()


def sha1(body: bytes) -> str:
    """Mojang's own hash of `body`."""
    return hashlib.sha1(body, usedforsecurity=False).hexdigest()


def version_json(jar: bytes) -> bytes:
    """26.3's version JSON, naming `jar` by its sha1 and size."""
    server = {"sha1": sha1(jar), "size": len(jar), "url": JAR_URL}
    return json.dumps({"id": "26.3", "downloads": {"server": server}}).encode()


def manifest(listed: bytes) -> bytes:
    """Mojang's version manifest, listing 26.3's version JSON `listed` by its sha1."""
    versions = [
        {"id": "26.4-snapshot-2", "type": "snapshot", "url": "https://x.example/a.json"},
        {"id": "26.3", "type": "release", "url": VERSION_URL, "sha1": sha1(listed)},
    ]
    return json.dumps({"latest": {"release": "26.3"}, "versions": versions}).encode()


class FakeMojang:
    """A fetch that serves the manifest, 26.3's version JSON and `served` as its jar.

    The manifest lists the version JSON of `jar` (by default, the one served), so a
    `served` that differs from `jar` is a download that is not the published one.
    """

    def __init__(self, served: bytes | None = None, jar: bytes | None = None) -> None:
        served = fake_jar() if served is None else served
        listed = version_json(served if jar is None else jar)
        self.bodies = {MANIFEST_URL: manifest(listed), VERSION_URL: listed, JAR_URL: served}
        self.fetched: list[str] = []

    def __call__(self, url: str) -> Download:
        self.fetched.append(url)
        return Download(url=url, body=self.bodies[url])
