"""Research jars use fake downloads; these tests never invoke Java or the network."""

import hashlib
import importlib.util
import io
import json
import subprocess
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


def _sha1(body: bytes) -> str:
    return hashlib.sha1(body, usedforsecurity=False).hexdigest()


class Downloads:
    def __init__(self, body: bytes = b"client jar", side: str = "client") -> None:
        self.calls: list[str] = []
        version = json.dumps(
            {
                "downloads": {
                    side: {
                        "url": _JAR,
                        "sha1": hashlib.sha1(body, usedforsecurity=False).hexdigest(),
                        "size": len(body),
                    }
                }
            }
        ).encode()
        manifest = {"versions": [{"id": "26.3", "url": _VERSION, "sha1": _sha1(version)}]}
        self.responses = {
            _MANIFEST: json.dumps(manifest).encode(),
            _VERSION: version,
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


def test_a_version_json_that_differs_from_its_manifest_sha1_is_refused(
    javap: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MSCTS_CACHE", str(tmp_path))
    downloads = Downloads()
    downloads.responses[_VERSION] += b" "

    with pytest.raises(ProvisionError, match="differs from its manifest sha1"):
        javap.cached_jar("client", downloads)
    assert _JAR not in downloads.calls


@pytest.mark.parametrize("verbose", [False, True])
def test_main_uses_the_selected_jdk_and_passes_through_javap_status(
    javap: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, verbose: bool
) -> None:
    jdk = tmp_path / "jdk with spaces"
    (jdk / "bin").mkdir(parents=True)
    (jdk / "release").write_text('JAVA_VERSION="25.0.4.1"\n')
    java = jdk / "bin" / "java"
    java.touch()
    executable = jdk / "bin" / "javap"
    executable.touch()
    monkeypatch.setenv("MSCTS_JAVA", str(java))
    jar = tmp_path / "client.jar"
    sides: list[str] = []

    def fake_classpath(side: str) -> Path:
        sides.append(side)
        return jar

    calls: list[list[str]] = []

    def fake_run(argv: list[str], *, check: bool) -> subprocess.CompletedProcess[bytes]:
        assert check is False
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 7)

    monkeypatch.setattr(javap, "classpath", fake_classpath)
    monkeypatch.setattr(javap, "_run", fake_run)
    classes = ["net.minecraft.client.Minecraft", "net.minecraft.Example$Inner"]

    assert javap.main(["client", *classes, *(["-v"] if verbose else [])]) == 7
    assert sides == ["client"]
    assert calls == [
        [
            str(executable),
            "-c",
            "-p",
            "-constants",
            *(["-v"] if verbose else []),
            "-classpath",
            str(jar),
            *classes,
        ]
    ]


@pytest.mark.parametrize(
    "args",
    [[], ["client"], ["other", "SomeClass"], ["client", "-x"], ["client", "--", "-Weird"]],
    ids=["no-args", "no-class", "bad-side", "unknown-option", "class-like-option"],
)
def test_main_rejects_argument_errors_before_downloads(
    javap: types.ModuleType, args: list[str]
) -> None:
    with pytest.raises(SystemExit) as error:
        javap.main(args)
    assert error.value.code == 2


def test_main_reports_missing_javap_before_downloading(
    javap: types.ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "bin").mkdir()
    java = tmp_path / "bin" / "java"
    java.touch()
    (tmp_path / "release").write_text('JAVA_VERSION="25"\n')
    monkeypatch.setenv("MSCTS_JAVA", str(java))

    assert javap.main(["client", "SomeClass"]) == 1
    assert "javap" in capsys.readouterr().err


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
