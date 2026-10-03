"""Inspect the Target with javap using verified jars; --out DIR saves one .txt per class."""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from subprocess import run as _run

from mscts import cache
from mscts.adapters.base import Fetch, PrepareError, ProvisionError
from mscts.adapters.fetch import https_get
from mscts.adapters.vanilla import resolve_java
from mscts.target import TARGET

_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        msg = "expected a JSON object in Mojang metadata"
        raise ProvisionError(msg)
    return {str(key): item for key, item in value.items()}


def _string(fields: dict[str, object], key: str) -> str:
    value = fields.get(key)
    if not isinstance(value, str):
        msg = f"Mojang metadata has no string {key!r}"
        raise ProvisionError(msg)
    return value


@dataclass(frozen=True, slots=True)
class _Artifact:
    """A jar Mojang publishes, by its URL and the sha1 and size it lists."""

    url: str
    sha1: str
    size: int

    def matches(self, body: bytes) -> bool:
        """Whether `body` has the sha1 and size Mojang lists (its integrity check)."""
        sha1 = hashlib.sha1(body, usedforsecurity=False).hexdigest()
        return len(body) == self.size and sha1 == self.sha1


def _entry(metadata: bytes) -> _Artifact:
    fields = _object(json.loads(metadata))
    sha1 = _string(fields, "sha1")
    size = fields.get("size")
    if re.fullmatch(r"[0-9a-f]{40}", sha1) is None or type(size) is not int or size <= 0:
        msg = "Mojang download metadata needs a sha1 and positive size"
        raise ProvisionError(msg)
    return _Artifact(url=_string(fields, "url"), sha1=sha1, size=size)


def _version(fetch: Fetch) -> dict[str, object]:
    manifest = _object(json.loads(fetch(_MANIFEST).body))
    versions = manifest.get("versions")
    if not isinstance(versions, list):
        msg = "Mojang manifest has no versions list"
        raise ProvisionError(msg)
    for version in versions:
        fields = _object(version)
        if fields.get("id") == TARGET.minecraft_version:
            # The version document supplies the jar hashes, so it is verified by the sha1
            # the manifest lists for it before anything in it is trusted.
            body = fetch(_string(fields, "url")).body
            if hashlib.sha1(body, usedforsecurity=False).hexdigest() != _string(fields, "sha1"):
                msg = f"the {TARGET.minecraft_version} version JSON differs from its manifest sha1"
                raise ProvisionError(msg)
            return _object(json.loads(body))
    msg = f"Mojang manifest has no {TARGET.minecraft_version}"
    raise ProvisionError(msg)


def _metadata(side: str, fetch: Fetch) -> bytes:
    downloads = _object(_version(fetch).get("downloads"))
    return json.dumps(_object(downloads.get(side))).encode()


def _write(path: Path, body: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix=".part")
    part = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(body)
        part.replace(path)
    finally:
        part.unlink(missing_ok=True)


def cached_jar(side: str, fetch: Fetch = https_get) -> Path:
    """Fetch a Target jar once; verify its publisher's sha1 and size on every use."""
    if side not in {"client", "server"}:
        msg = f"expected client or server, got {side!r}"
        raise ValueError(msg)
    root = cache.cache_dir() / "research" / TARGET.minecraft_version
    root.mkdir(parents=True, exist_ok=True)
    metadata_path = root / f"{side}.json"
    metadata = metadata_path.read_bytes() if metadata_path.exists() else _metadata(side, fetch)
    entry = _entry(metadata)
    jar = root / f"{side}.jar"
    body = jar.read_bytes() if jar.exists() else fetch(entry.url).body
    if not entry.matches(body):
        msg = f"{jar}: sha1 or size differs from Mojang metadata; delete {jar} and retry"
        raise ProvisionError(msg)
    if not jar.exists():
        _write(jar, body)
    if not metadata_path.exists():
        _write(metadata_path, metadata)
    return jar


def _library_entries(fetch: Fetch) -> dict[str, _Artifact]:
    root = cache.cache_dir() / "research" / TARGET.minecraft_version
    root.mkdir(parents=True, exist_ok=True)
    metadata_path = root / "libraries.json"
    if metadata_path.exists():
        libraries: object = json.loads(metadata_path.read_bytes())
    else:
        libraries = _version(fetch).get("libraries")
    if not isinstance(libraries, list):
        msg = "Mojang version metadata has no libraries list"
        raise ProvisionError(msg)
    artifacts: dict[str, _Artifact] = {}
    for library in libraries:
        fields = _object(library)
        downloads = _object(fields.get("downloads"))
        if "artifact" in downloads:
            name = _string(fields, "name")
            artifacts[name] = _entry(json.dumps(downloads["artifact"]).encode())
    if not metadata_path.exists():
        _write(metadata_path, json.dumps(libraries).encode())
    return artifacts


def cached_libraries(patterns: list[str], fetch: Fetch = https_get) -> list[Path]:
    """Resolve each artifact substring once; verify every selected jar on every use."""
    if not patterns:
        return []
    artifacts = _library_entries(fetch)
    selected: dict[str, _Artifact] = {}
    for pattern in patterns:
        matches = [name for name in artifacts if pattern in name]
        if len(matches) != 1:
            found = ", ".join(sorted(matches)) or "none"
            msg = f"--lib {pattern!r} needs one artifact match; found {found}"
            raise ProvisionError(msg)
        name = matches[0]
        selected[name] = artifacts[name]
    directory = cache.cache_dir() / "research" / TARGET.minecraft_version / "libraries"
    directory.mkdir(exist_ok=True)
    jars: list[Path] = []
    for entry in selected.values():
        jar = directory / f"{entry.sha1}.jar"
        body = jar.read_bytes() if jar.exists() else fetch(entry.url).body
        if not entry.matches(body):
            msg = f"{jar}: sha1 or size differs from Mojang metadata; delete {jar} and retry"
            raise ProvisionError(msg)
        if not jar.exists():
            _write(jar, body)
        jars.append(jar)
    return jars


def classpath(side: str, fetch: Fetch = https_get) -> Path:
    """The client jar or the server's inner jar, extracted from the verified bundle."""
    jar = cached_jar(side, fetch)
    if side == "client":
        return jar
    version = TARGET.minecraft_version
    member = f"META-INF/versions/{version}/server-{version}.jar"
    try:
        with zipfile.ZipFile(jar) as archive:
            body = archive.read(member)
    except (zipfile.BadZipFile, KeyError) as error:
        msg = f"{jar} has no readable {member}: {error}"
        raise ProvisionError(msg) from error
    inner = jar.with_name(f"server-{version}.jar")
    if not inner.exists() or inner.read_bytes() != body:
        _write(inner, body)
    return inner


def _executable() -> Path:
    executable = resolve_java(TARGET).with_name("javap")
    if not executable.is_file():
        msg = f"{executable} is missing; set MSCTS_JAVA to a Java {TARGET.java_major} JDK"
        raise PrepareError(msg)
    return executable


def main(argv: list[str] | None = None) -> int:
    """Print javap output for the requested classes and return its exit status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("side", choices=("client", "server"))
    parser.add_argument("classes", nargs="+", metavar="Class")
    parser.add_argument("-v", action="store_true", help="include the verbose constant pool")
    parser.add_argument("--out", type=Path, help="write one CLASS.txt file per class in DIR")
    parser.add_argument(
        "--lib",
        action="append",
        default=[],
        metavar="ARTIFACT",
        help="add the one library matching this artifact substring; repeatable",
    )
    args = parser.parse_args(argv)
    if any(name.startswith("-") for name in args.classes):
        parser.error("class names cannot start with '-'")
    if args.out is not None and any("/" in name or "\\" in name for name in args.classes):
        parser.error("class names cannot contain path separators")
    try:
        executable = _executable()
        jar = classpath(args.side)
        libraries = cached_libraries(args.lib)
        command = [str(executable), "-c", "-p", "-constants"]
        if args.v:
            command.append("-v")
        paths = os.pathsep.join(str(path) for path in [jar, *libraries])
        command.extend(["-classpath", paths])
        if args.out is not None:
            args.out.mkdir(parents=True, exist_ok=True)
            status = 0
            for name in args.classes:
                with (args.out / f"{name}.txt").open("w", encoding="utf-8") as sink:
                    result = _run([*command, name], stdout=sink, check=False)  # noqa: S603
                status = status or result.returncode
            return status
        command.extend(args.classes)
        # The selected JDK's absolute executable, with separate arguments and no shell.
        return _run(command, check=False).returncode  # noqa: S603
    except (OSError, ValueError, PrepareError, ProvisionError) as error:
        print(f"javap.py: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
