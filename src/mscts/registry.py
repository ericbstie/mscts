"""The Registry: the maintainer-approved servers `mscts adapter install` can download.

Each Entry is pinned by checksum (ADR-0008): a name or a URL alone is never trusted.
The committed list is `data/registry.toml`; it is read strictly, so a typo is an error,
never a silently ignored key.
"""

import hashlib
import re
import tomllib
from dataclasses import dataclass
from importlib import resources
from typing import override
from urllib.parse import urlsplit

from mscts.target import Target

_HEX_DIGITS = {"sha256": 64, "sha1": 40}
_REQUIRED = ("adapter", "version", "target", "url")
_OPTIONAL = ("sha256", "sha1", "size", "note")


class RegistryError(ValueError):
    """The Registry is malformed, or has no entry for what was asked."""


@dataclass(frozen=True, slots=True)
class Entry:
    """One installable server build, pinned by sha256 and/or its publisher's hash."""

    adapter: str  # the Adapter that runs it ("pumpkin")
    version: str  # the label `--version` names ("26.3", "nightly-48cba7ee")
    target: str  # the Target's Minecraft version it speaks
    url: str  # HTTPS only
    sha256: str | None = None
    sha1: str | None = None  # the publisher's hash (Mojang publishes SHA-1)
    size: int | None = None  # bytes, where the publisher states it
    note: str = ""

    @override
    def __str__(self) -> str:
        """`pumpkin nightly-48cba7ee`: how commands name this entry."""
        return f"{self.adapter} {self.version}"

    def matches(self, body: bytes) -> bool:
        """Whether `body` is this build: every hash (and the size) the entry pins agrees."""
        if self.size is not None and len(body) != self.size:
            return False
        if self.sha256 is not None and hashlib.sha256(body).hexdigest() != self.sha256:
            return False
        # SHA-1 is Mojang's integrity check here, not a security boundary.
        return self.sha1 is None or hashlib.sha1(body, usedforsecurity=False).hexdigest() == (
            self.sha1
        )


@dataclass(frozen=True, slots=True)
class Registry:
    """Every Entry, in file order."""

    entries: tuple[Entry, ...]

    def resolve(self, adapter: str, target: Target, version: str | None = None) -> Entry:
        """The entry `version` of `adapter`, else its only entry for `target`.

        RegistryError, naming what would work, if there is no such entry or several.
        """
        known = [entry for entry in self.entries if entry.adapter == adapter]
        if not known:
            adapters = ", ".join(sorted({entry.adapter for entry in self.entries}))
            msg = f"no registry entry for {adapter}; known Adapters: {adapters}"
            raise RegistryError(msg)
        labels = ", ".join(entry.version for entry in known)
        if version is not None:
            for entry in known:
                if entry.version == version:
                    return entry
            msg = f"{adapter} has no registry entry {version}; its entries: {labels}"
            raise RegistryError(msg)
        current = [entry for entry in known if entry.target == target.minecraft_version]
        if len(current) == 1:
            return current[0]
        if not current:
            msg = (
                f"{adapter} has registry entries ({labels}) but none for "
                f"{target.minecraft_version}, the Target"
            )
            raise RegistryError(msg)
        choices = " or ".join(f"--version {entry.version}" for entry in current)
        msg = f"{adapter} has several entries for {target.minecraft_version}: pass {choices}"
        raise RegistryError(msg)


def _strings(where: str, fields: dict[str, object]) -> dict[str, str]:
    """The string keys of one entry's `fields`, each checked for presence and type."""
    for key in fields:
        if key not in _REQUIRED + _OPTIONAL:
            msg = f"{where}: unknown key {key!r}"
            raise RegistryError(msg)
    strings: dict[str, str] = {}
    for key in (*_REQUIRED, "sha256", "sha1", "note"):
        value = fields.get(key)
        if value is None and key in _REQUIRED:
            msg = f"{where}: missing {key!r}"
            raise RegistryError(msg)
        if value is not None and not isinstance(value, str):
            msg = f"{where}: {key!r} must be a string"
            raise RegistryError(msg)
        if isinstance(value, str):
            strings[key] = value
    return strings


def _entry(index: int, table: object) -> Entry:
    where = f"registry entry #{index + 1}"
    if not isinstance(table, dict):
        msg = f"{where} is not a table"
        raise RegistryError(msg)
    fields: dict[str, object] = {str(key): value for key, value in table.items()}
    strings = _strings(where, fields)
    for key, digits in _HEX_DIGITS.items():
        if key in strings and not re.fullmatch(f"[0-9a-f]{{{digits}}}", strings[key]):
            msg = f"{where}: {key} must be {digits} lowercase hex digits"
            raise RegistryError(msg)
    if "sha256" not in strings and "sha1" not in strings:
        msg = f"{where}: no hash; an entry pins sha256 and/or sha1"
        raise RegistryError(msg)
    if urlsplit(strings["url"]).scheme != "https":
        msg = f"{where}: {strings['url']} is not an HTTPS URL"
        raise RegistryError(msg)
    size = fields.get("size")
    if size is not None and (type(size) is not int or size <= 0):
        msg = f"{where}: 'size' must be a positive integer"
        raise RegistryError(msg)
    return Entry(
        adapter=strings["adapter"],
        version=strings["version"],
        target=strings["target"],
        url=strings["url"],
        sha256=strings.get("sha256"),
        sha1=strings.get("sha1"),
        size=size if type(size) is int else None,
        note=strings.get("note", ""),
    )


def parse(text: str) -> Registry:
    """The Registry in `text` (TOML), checked strictly: RegistryError on any flaw."""
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        msg = f"the registry is not valid TOML: {error}"
        raise RegistryError(msg) from error
    for key in document:
        if key != "entry":
            msg = f"unknown top-level key {key!r} in the registry"
            raise RegistryError(msg)
    tables: object = document.get("entry", [])
    if not isinstance(tables, list):
        msg = "the registry's 'entry' must be a list of [[entry]] tables"
        raise RegistryError(msg)
    entries: list[Entry] = []
    for index, table in enumerate(tables):
        entry = _entry(index, table)
        if any((e.adapter, e.version) == (entry.adapter, entry.version) for e in entries):
            msg = f"duplicate entry {entry} in the registry"
            raise RegistryError(msg)
        entries.append(entry)
    return Registry(entries=tuple(entries))


def official() -> Registry:
    """The committed Registry, `mscts/data/registry.toml`."""
    committed = resources.files("mscts").joinpath("data", "registry.toml")
    return parse(committed.read_text(encoding="utf-8"))
