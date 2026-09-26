import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from mscts.adapters.base import ProvisionError
from mscts.adapters.fetch import Download
from mscts.adapters.vanilla import VanillaAdapter
from mscts.install import install_entry
from mscts.registry import Entry
from mscts.target import TARGET

JAR_URL = "https://piston-data.example/v1/objects/def/server.jar"


ZIP_DATE = (2026, 1, 1, 0, 0, 0)


def fake_jar(protocol_version: int = 777) -> bytes:
    """A tiny stand-in for the server jar: a zip whose version.json names the protocol.

    Its entries carry a fixed date, so the bytes never depend on the clock: pytest-xdist
    workers collecting at different seconds must see the same parametrized tests.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as jar:
        version = {"id": "26.3", "protocol_version": protocol_version, "java_version": 25}
        jar.writestr(zipfile.ZipInfo("version.json", ZIP_DATE), json.dumps(version))
        jar.writestr(
            zipfile.ZipInfo("net/minecraft/bundler/Main.class", ZIP_DATE), b"\xca\xfe\xba\xbe"
        )
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


PINNED = fake_jar()
ENTRY = entry_for(PINNED)


def test_install_entry_installs_the_pinned_jar_into_the_cache(tmp_path: Path) -> None:
    mojang = FakeMojang(PINNED)
    done = install_entry(VanillaAdapter(), TARGET, tmp_path, ENTRY, mojang)
    installation = done.installation
    assert (installation.adapter, installation.target) == ("vanilla", TARGET)
    assert installation.root == tmp_path / "vanilla/26.3"
    assert installation.source is not None
    assert installation.source.entry == "vanilla 26.3"
    assert (installation.root / "server.jar").read_bytes() == PINNED
    assert mojang.fetched == [JAR_URL]


@pytest.mark.parametrize(
    "served",
    [
        # Same size, different bytes from those the published sha1 names.
        PINNED[:-1] + bytes([PINNED[-1] ^ 0xFF]),
        PINNED + b"\0",
    ],
    ids=["same-size-other-bytes", "one-byte-longer"],
)
def test_install_entry_rejects_a_download_that_is_not_the_pinned_jar(
    tmp_path: Path, served: bytes
) -> None:
    assert served != PINNED
    with pytest.raises(ProvisionError, match=r"is not vanilla 26\.3"):
        install_entry(VanillaAdapter(), TARGET, tmp_path, ENTRY, FakeMojang(served))
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
