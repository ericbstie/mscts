import dataclasses
import hashlib

import pytest

from mscts import registry
from mscts.registry import Entry, RegistryError, parse
from mscts.target import TARGET

SHA256 = "a" * 64
SHA1 = "b" * 40

ONE = f"""
[[entry]]
adapter = "pumpkin"
version = "nightly-aaaaaaaa"
target = "26.3"
url = "https://example.com/pumpkin"
sha256 = "{SHA256}"
note = "a pinned nightly"
"""


def test_parse_reads_an_entry() -> None:
    assert parse(ONE).entries == (
        Entry(
            adapter="pumpkin",
            version="nightly-aaaaaaaa",
            target="26.3",
            url="https://example.com/pumpkin",
            sha256=SHA256,
            note="a pinned nightly",
        ),
    )


@pytest.mark.parametrize(
    ("text", "error"),
    [
        (ONE + 'colour = "red"\n', "unknown key 'colour'"),
        ("[meta]\nx = 1\n" + ONE, "unknown top-level key 'meta'"),
        (ONE.replace(f'sha256 = "{SHA256}"\n', ""), "no hash"),
        (ONE.replace('url = "https://example.com/pumpkin"\n', ""), "missing 'url'"),
        (ONE + ONE, "duplicate entry pumpkin nightly-aaaaaaaa"),
        (ONE.replace("https://", "http://"), "not an HTTPS URL"),
        (ONE.replace(SHA256, "A" * 64), "sha256 must be 64 lowercase hex"),
        (ONE.replace(f'sha256 = "{SHA256}"', 'sha1 = "abc"'), "sha1 must be 40 lowercase hex"),
        (ONE.replace('target = "26.3"', "target = 26.3"), "'target' must be a string"),
        (ONE + "size = -1\n", "'size' must be a positive integer"),
        ("entry = 1\n", "must be a list of"),
        ("[[entry\n", "not valid TOML"),
    ],
)
def test_parse_is_strict(text: str, error: str) -> None:
    with pytest.raises(RegistryError, match=error):
        parse(text)


def test_an_entry_hash_matches_by_every_hash_it_pins() -> None:
    body = b"\x7fELF a build"
    both = Entry(
        adapter="x",
        version="1",
        target="26.3",
        url="https://example.com/x",
        sha256=hashlib.sha256(body).hexdigest(),
        sha1=hashlib.sha1(body, usedforsecurity=False).hexdigest(),
        size=len(body),
    )
    assert both.matches(body)
    assert not both.matches(body + b"!")
    assert not dataclasses.replace(both, sha1=SHA1).matches(body)
    assert not dataclasses.replace(both, sha256=SHA256).matches(body)
    assert not dataclasses.replace(both, size=len(body) + 1).matches(body)


TWO = ONE + ONE.replace("nightly-aaaaaaaa", "nightly-cccccccc")


def test_resolve_picks_the_one_entry_for_the_target() -> None:
    assert parse(ONE).resolve("pumpkin", TARGET).version == "nightly-aaaaaaaa"


def test_resolve_picks_a_named_version() -> None:
    entry = parse(TWO).resolve("pumpkin", TARGET, "nightly-cccccccc")
    assert entry.version == "nightly-cccccccc"


@pytest.mark.parametrize(
    ("text", "adapter", "version", "error"),
    [
        (ONE, "paper", None, "no registry entry for paper.*known Adapters: pumpkin"),
        (ONE, "pumpkin", "9", "pumpkin has no registry entry 9.*nightly-aaaaaaaa"),
        (TWO, "pumpkin", None, "--version nightly-aaaaaaaa.*--version nightly-cccccccc"),
        (ONE.replace('"26.3"', '"26.2"'), "pumpkin", None, "none for 26.3"),
    ],
)
def test_resolve_errors_name_the_fix(
    text: str, adapter: str, version: str | None, error: str
) -> None:
    with pytest.raises(RegistryError, match=error):
        parse(text).resolve(adapter, TARGET, version)


def test_the_committed_registry_pins_vanilla_by_mojangs_sha1() -> None:
    vanilla = registry.official().resolve("vanilla", TARGET)
    assert (vanilla.version, vanilla.url, vanilla.sha1, vanilla.size) == (
        "26.3",
        "https://piston-data.mojang.com/v1/objects/33680f5f2ac32864d6d7cf5e56a705fdb3e05f4c/server.jar",
        "33680f5f2ac32864d6d7cf5e56a705fdb3e05f4c",
        62294556,
    )


def test_the_committed_registry_pins_one_pumpkin_nightly_build_by_sha256() -> None:
    pumpkin = registry.official().resolve("pumpkin", TARGET)
    assert (pumpkin.url, pumpkin.sha256) == (
        "https://github.com/Pumpkin-MC/Pumpkin/releases/download/nightly/pumpkin-X64-Linux",
        "48cba7ee6e255f7d2150435f58228f1ec9cab477f1dee259f47cd24b8f304b0b",
    )
    assert "moves" in pumpkin.note  # a mismatch means the nightly moved
