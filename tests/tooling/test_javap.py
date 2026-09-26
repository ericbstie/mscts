"""Research jars use fake downloads; these tests never invoke Java or the network."""

import hashlib
import importlib.util
import io
import json
import types
import zipfile
from pathlib import Path

import pytest

from mscts.adapters.base import ProvisionError
from mscts.adapters.fetch import Download

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "research" / "javap.py"
_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
_VERSION = "https://example.test/26.3.json"
_JAR = "https://example.test/client.jar"


@pytest.fixture
def javap() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("javap", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Downloads:
    def __init__(self, body: bytes = b"client jar", side: str = "client") -> None:
        self.calls: list[str] = []
        self.responses = {
            _MANIFEST: json.dumps({"versions": [{"id": "26.3", "url": _VERSION}]}).encode(),
            _VERSION: json.dumps(
                {
                    "downloads": {
                        side: {
                            "url": _JAR,
                            "sha1": hashlib.sha1(body, usedforsecurity=False).hexdigest(),
                            "size": len(body),
                        }
                    }
                }
            ).encode(),
            _JAR: body,
        }

    def __call__(self, url: str) -> Download:
        self.calls.append(url)
        return Download(url, self.responses[url])


def test_client_jar_is_verified_and_reused_offline(
    javap: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MSCTS_CACHE", str(tmp_path))
    downloads = Downloads()

    jar = javap.cached_jar("client", downloads)

    assert jar.is_relative_to(tmp_path)
    assert jar.read_bytes() == b"client jar"
    assert downloads.calls == [_MANIFEST, _VERSION, _JAR]
    downloads.responses.clear()
    assert javap.cached_jar("client", downloads) == jar
    assert downloads.calls == [_MANIFEST, _VERSION, _JAR]


def test_server_classpath_extracts_only_the_inner_jar_and_reuses_it(
    javap: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MSCTS_CACHE", str(tmp_path))
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("META-INF/versions/26.3/server-26.3.jar", b"inner jar")
        archive.writestr("../outside.txt", b"never extract this")
    downloads = Downloads(stream.getvalue(), "server")

    jar = javap.classpath("server", downloads)

    assert jar.is_relative_to(tmp_path)
    assert jar.name == "server-26.3.jar"
    assert jar.read_bytes() == b"inner jar"
    assert not list(tmp_path.rglob("outside.txt"))
    modified = jar.stat().st_mtime_ns
    downloads.responses.clear()
    assert javap.classpath("server", downloads) == jar
    assert jar.stat().st_mtime_ns == modified
    jar.write_bytes(b"corrupt inner jar")
    assert javap.classpath("server", downloads).read_bytes() == b"inner jar"
    assert downloads.calls == [_MANIFEST, _VERSION, _JAR]


def test_server_requires_the_target_inner_jar(
    javap: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MSCTS_CACHE", str(tmp_path))
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("META-INF/versions/old/server-old.jar", b"wrong version")

    with pytest.raises(ProvisionError, match=r"server-26\.3\.jar"):
        javap.classpath("server", Downloads(stream.getvalue(), "server"))


def test_sha1_mismatch_is_not_cached(
    javap: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MSCTS_CACHE", str(tmp_path))
    downloads = Downloads()
    downloads.responses[_JAR] = b"broken jar"

    with pytest.raises(ProvisionError, match="sha1"):
        javap.cached_jar("client", downloads)

    assert not list(tmp_path.rglob("*.jar"))


def test_cached_jar_is_checked_again_without_network(
    javap: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MSCTS_CACHE", str(tmp_path))
    downloads = Downloads()
    jar = javap.cached_jar("client", downloads)
    jar.write_bytes(b"broken jar")
    downloads.responses.clear()

    with pytest.raises(ProvisionError, match="sha1"):
        javap.cached_jar("client", downloads)

    assert downloads.calls == [_MANIFEST, _VERSION, _JAR]
