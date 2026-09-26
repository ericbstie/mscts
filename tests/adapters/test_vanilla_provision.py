import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from mscts import registry
from mscts.adapters.base import Adapter, ProvisionError
from mscts.adapters.fetch import Download
from mscts.adapters.vanilla import VanillaAdapter
from mscts.registry import Entry, Registry
from mscts.target import TARGET

JAR_URL = "https://piston-data.example/v1/objects/def/server.jar"


def fake_jar(protocol_version: int = 777) -> bytes:
    """A tiny stand-in for the server jar: a zip whose version.json names the protocol."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as jar:
        version = {"id": "26.3", "protocol_version": protocol_version, "java_version": 25}
        jar.writestr("version.json", json.dumps(version))
        jar.writestr("net/minecraft/bundler/Main.class", b"\xca\xfe\xba\xbe")
    return buffer.getvalue()


def entry_for(jar: bytes) -> Entry:
    """A vanilla Registry entry pinning `jar` as Mojang pins a jar: by sha1 and size."""
    return Entry(
        adapter="vanilla",
        version="26.3",
        target="26.3",
        url=JAR_URL,
        sha1=hashlib.sha1(jar, usedforsecurity=False).hexdigest(),
        size=len(jar),
    )


class FakeMojang:
    """A fetch that serves one jar and records every URL it was asked for."""

    def __init__(self, jar: bytes) -> None:
        self.jar = jar
        self.fetched: list[str] = []

    def __call__(self, url: str) -> Download:
        self.fetched.append(url)
        return Download(url=url, body=self.jar)


@pytest.fixture
def pinned(monkeypatch: pytest.MonkeyPatch) -> bytes:
    """The Registry pins fake_jar(); return it."""
    jar = fake_jar()
    monkeypatch.setattr(registry, "official", lambda: Registry(entries=(entry_for(jar),)))
    return jar


def test_provision_installs_the_registry_jar_into_the_cache(tmp_path: Path, pinned: bytes) -> None:
    mojang = FakeMojang(pinned)
    adapter: Adapter = VanillaAdapter(fetch=mojang)
    installation = adapter.provision(TARGET, tmp_path)
    assert (installation.adapter, installation.target) == ("vanilla", TARGET)
    assert installation.root == tmp_path / "vanilla/26.3"
    assert installation.source is not None
    assert installation.source.entry == "vanilla 26.3"
    assert (installation.root / "server.jar").read_bytes() == pinned
    assert mojang.fetched == [JAR_URL]


def test_provision_reuses_an_installed_jar(tmp_path: Path, pinned: bytes) -> None:
    VanillaAdapter(fetch=FakeMojang(pinned)).provision(TARGET, tmp_path)
    again = FakeMojang(pinned)
    VanillaAdapter(fetch=again).provision(TARGET, tmp_path)
    assert again.fetched == []


@pytest.mark.parametrize(
    "served",
    [
        # Same size, different bytes from those the published sha1 names.
        fake_jar()[:-1] + bytes([fake_jar()[-1] ^ 0xFF]),
        fake_jar() + b"\0",
    ],
)
def test_provision_rejects_a_download_that_is_not_the_pinned_jar(
    tmp_path: Path, pinned: bytes, served: bytes
) -> None:
    assert served != pinned
    with pytest.raises(ProvisionError, match=r"is not vanilla 26\.3"):
        VanillaAdapter(fetch=FakeMojang(served)).provision(TARGET, tmp_path)
    assert not (tmp_path / "vanilla/26.3").exists()


@pytest.mark.parametrize(
    ("jar", "error"),
    [(fake_jar(protocol_version=778), "speaks protocol 778"), (b"PK not a zip", "not a vanilla")],
)
def test_check_refuses_a_jar_that_is_not_a_server_for_the_target(
    tmp_path: Path, jar: bytes, error: str
) -> None:
    (tmp_path / "server.jar").write_bytes(jar)
    with pytest.raises(ProvisionError, match=error):
        VanillaAdapter().check(tmp_path / "server.jar", TARGET)
