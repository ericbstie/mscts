"""Inspect the Target's vanilla client or server with javap, using verified cached jars."""

import argparse
import json
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path
from subprocess import run as _run

from mscts import cache
from mscts.adapters.base import PrepareError, ProvisionError
from mscts.adapters.fetch import Fetch, https_get
from mscts.adapters.vanilla import resolve_java
from mscts.registry import Entry
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


def _entry(side: str, metadata: bytes) -> Entry:
    fields = _object(json.loads(metadata))
    sha1 = _string(fields, "sha1")
    size = fields.get("size")
    if re.fullmatch(r"[0-9a-f]{40}", sha1) is None or type(size) is not int or size <= 0:
        msg = "Mojang download metadata needs a sha1 and positive size"
        raise ProvisionError(msg)
    return Entry(
        adapter=side,
        version=TARGET.minecraft_version,
        target=TARGET.minecraft_version,
        url=_string(fields, "url"),
        sha1=sha1,
        size=size,
    )


def _metadata(side: str, fetch: Fetch) -> bytes:
    manifest = _object(json.loads(fetch(_MANIFEST).body))
    versions = manifest.get("versions")
    if not isinstance(versions, list):
        msg = "Mojang manifest has no versions list"
        raise ProvisionError(msg)
    for version in versions:
        fields = _object(version)
        if fields.get("id") == TARGET.minecraft_version:
            document = _object(json.loads(fetch(_string(fields, "url")).body))
            downloads = _object(document.get("downloads"))
            return json.dumps(_object(downloads.get(side))).encode()
    msg = f"Mojang manifest has no {TARGET.minecraft_version}"
    raise ProvisionError(msg)


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
    entry = _entry(side, metadata)
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
    args = parser.parse_args(argv)
    if any(name.startswith("-") for name in args.classes):
        parser.error("class names cannot start with '-'")
    try:
        executable = _executable()
        jar = classpath(args.side)
        command = [str(executable), "-c", "-p", "-constants"]
        if args.v:
            command.append("-v")
        command.extend(["-classpath", str(jar), *args.classes])
        # The selected JDK's absolute executable, with separate arguments and no shell.
        return _run(command, check=False).returncode  # noqa: S603
    except (OSError, ValueError, PrepareError, ProvisionError) as error:
        print(f"javap.py: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
