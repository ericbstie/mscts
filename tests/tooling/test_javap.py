"""Research jars use fake downloads; these tests never invoke Java or the network."""

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import types
import zipfile
from pathlib import Path
from typing import TextIO

import pytest

from mscts.adapters.base import Download, ProvisionError

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


def _libraries(names: tuple[str, ...] = ("com.mojang:datafixerupper:8.0.16",)) -> Downloads:
    downloads = Downloads()
    version = json.loads(downloads.responses[_VERSION])
    version["libraries"] = [
        {
            "name": name,
            "downloads": {
                "artifact": {
                    "url": f"https://example.test/lib-{index}.jar",
                    "sha1": _sha1(name.encode()),
                    "size": len(name.encode()),
                }
            },
        }
        for index, name in enumerate(names)
    ]
    downloads.responses[_VERSION] = json.dumps(version).encode()
    downloads.responses[_MANIFEST] = json.dumps(
        {
            "versions": [
                {"id": "26.3", "url": _VERSION, "sha1": _sha1(downloads.responses[_VERSION])}
            ]
        }
    ).encode()
    for index, name in enumerate(names):
        downloads.responses[f"https://example.test/lib-{index}.jar"] = name.encode()
    return downloads


def test_library_selection_downloads_and_reuses_verified_artifacts(
    javap: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MSCTS_CACHE", str(tmp_path))
    downloads = _libraries()
    url = "https://example.test/lib-0.jar"

    function = getattr(javap, "cached_libraries", None)
    assert callable(function), "cached_libraries must resolve and verify --lib artifacts"
    jars = function(["datafixerupper"], downloads)

    assert len(jars) == 1
    assert jars[0].parent == tmp_path / "research/26.3/libraries"
    assert jars[0].read_bytes() == b"com.mojang:datafixerupper:8.0.16"
    assert downloads.calls == [_MANIFEST, _VERSION, url]
    downloads.responses.clear()
    assert function(["datafixerupper"], downloads) == jars
    assert downloads.calls == [_MANIFEST, _VERSION, url]


@pytest.mark.parametrize("pattern", ["missing", "datafixerupper"], ids=["none", "several"])
def test_library_selection_requires_exactly_one_match(
    javap: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pattern: str
) -> None:
    monkeypatch.setenv("MSCTS_CACHE", str(tmp_path))
    names = ("com.mojang:datafixerupper:8.0.16", "com.mojang:datafixerupper:9.0.0")
    downloads = _libraries(names)

    with pytest.raises(ProvisionError, match="needs one artifact match") as error:
        javap.cached_libraries([pattern], downloads)

    message = str(error.value)
    if pattern == "missing":
        assert "found none" in message
    else:
        assert all(name in message for name in names)
    assert downloads.calls == [_MANIFEST, _VERSION]


@pytest.mark.parametrize("cached", [False, True], ids=["download", "cache"])
def test_library_sha1_mismatch_is_refused_on_every_use(
    javap: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, cached: bool
) -> None:
    monkeypatch.setenv("MSCTS_CACHE", str(tmp_path))
    downloads = _libraries()
    if cached:
        jar = javap.cached_libraries(["datafixerupper"], downloads)[0]
        jar.write_bytes(b"x" * jar.stat().st_size)
        downloads.responses.clear()
    else:
        url = "https://example.test/lib-0.jar"
        downloads.responses[url] = b"x" * len(downloads.responses[url])

    with pytest.raises(ProvisionError, match="sha1 or size"):
        javap.cached_libraries(["datafixerupper"], downloads)

    assert not list(tmp_path.rglob("*.part"))
    if not cached:
        assert not list(tmp_path.rglob("*.jar"))


def test_library_size_mismatch_is_refused_even_when_sha1_matches(
    javap: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MSCTS_CACHE", str(tmp_path))
    downloads = _libraries()
    javap.cached_libraries(["datafixerupper"], downloads)
    metadata = tmp_path / "research/26.3/libraries.json"
    libraries = json.loads(metadata.read_bytes())
    libraries[0]["downloads"]["artifact"]["size"] += 1
    metadata.write_text(json.dumps(libraries))
    downloads.responses.clear()

    with pytest.raises(ProvisionError, match="sha1 or size"):
        javap.cached_libraries(["datafixerupper"], downloads)


def test_library_metadata_is_verified_against_the_manifest(
    javap: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MSCTS_CACHE", str(tmp_path))
    downloads = _libraries()
    downloads.responses[_VERSION] += b" "

    with pytest.raises(ProvisionError, match="differs from its manifest sha1"):
        javap.cached_libraries(["datafixerupper"], downloads)

    assert downloads.calls == [_MANIFEST, _VERSION]
    assert not list(tmp_path.rglob("libraries.json"))


def test_repeated_library_selection_downloads_once_in_command_order(
    javap: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MSCTS_CACHE", str(tmp_path))
    names = ("com.mojang:datafixerupper:8.0.16", "com.google.code.gson:gson:2.13.2")
    downloads = _libraries(names)

    jars = javap.cached_libraries(["gson", "datafixerupper", "gson"], downloads)

    assert [jar.read_bytes() for jar in jars] == [names[1].encode(), names[0].encode()]
    assert downloads.calls == [
        _MANIFEST,
        _VERSION,
        "https://example.test/lib-1.jar",
        "https://example.test/lib-0.jar",
    ]


def test_no_library_selection_needs_no_metadata_or_network(javap: types.ModuleType) -> None:
    downloads = Downloads()
    downloads.responses.clear()

    assert javap.cached_libraries([], downloads) == []
    assert downloads.calls == []


def test_main_places_selected_libraries_after_the_target_jar_on_the_classpath(
    javap: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "jdk/bin/javap"
    jar = tmp_path / "server.jar"
    libraries = [tmp_path / "libraries/dfu.jar", tmp_path / "libraries/gson.jar"]
    monkeypatch.setattr(javap, "_executable", lambda: executable)
    monkeypatch.setattr(javap, "classpath", lambda _side: jar)

    def selected(patterns: list[str]) -> list[Path]:
        assert patterns == ["datafixerupper", "gson"]
        return libraries

    monkeypatch.setattr(javap, "cached_libraries", selected)
    calls: list[list[str]] = []

    def fake_run(argv: list[str], *, check: bool) -> subprocess.CompletedProcess[bytes]:
        assert check is False
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 7)

    monkeypatch.setattr(javap, "_run", fake_run)
    args = ["--lib", "datafixerupper", "--lib", "gson", "server", "com.mojang.Example$Inner"]
    try:
        status = javap.main(args)
    except SystemExit as error:
        status = error.code

    assert status == 7
    assert calls == [
        [
            str(executable),
            "-c",
            "-p",
            "-constants",
            "-classpath",
            os.pathsep.join(str(path) for path in [jar, *libraries]),
            "com.mojang.Example$Inner",
        ]
    ]


@pytest.mark.parametrize("failed", [False, True])
def test_out_writes_one_file_per_class_and_preserves_failure(
    javap: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, failed: bool
) -> None:
    monkeypatch.setattr(javap, "_executable", lambda: tmp_path / "javap")
    monkeypatch.setattr(javap, "classpath", lambda _side: tmp_path / "client.jar")
    monkeypatch.setattr(javap, "cached_libraries", lambda _patterns: [])
    names = ["net.minecraft.Foo$Inner", "net.minecraft.Bar"]
    calls: list[str] = []

    def fake_run(
        argv: list[str], *, check: bool, stdout: TextIO
    ) -> subprocess.CompletedProcess[bytes]:
        assert check is False
        calls.append(argv[-1])
        stdout.write(f"disassembled {argv[-1]}\n")
        return subprocess.CompletedProcess(argv, 7 if failed and len(calls) == 1 else 0)

    monkeypatch.setattr(javap, "_run", fake_run)
    out = tmp_path / "new" / "output"

    assert javap.main(["client", *names, "--out", str(out)]) == (7 if failed else 0)
    assert calls == names
    assert sorted(path.name for path in out.iterdir()) == sorted(f"{name}.txt" for name in names)
    for name in names:
        assert (out / f"{name}.txt").read_text() == f"disassembled {name}\n"


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
