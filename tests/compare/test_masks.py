"""Masks: what a valid one is, and what it removes from a Comparison."""

import re

import pytest

from mscts.compare import Mask, compare
from tests.compare.build import packet, transcript

REASON = "nondeterministic in vanilla"
AWKWARD_KEYS = ["a.b", "", 'say "hi"', "\xe9", "]", '["x"]', "1", "a b", "\\", "\n"]


def test_every_divergence_path_is_a_valid_mask_path() -> None:
    def fields(value: int) -> dict[str, object]:
        return {"m": {key: [{key: value}] for key in AWKWARD_KEYS}}

    verdict = compare(
        transcript(("alice", packet("test:p", fields=fields(1)))),
        transcript(("alice", packet("test:p", fields=fields(2)))),
        [],
    )
    paths = [d.path for d in verdict.divergences]
    assert len(paths) == len(AWKWARD_KEYS)
    for path in paths:
        assert path is not None
        assert Mask(packet="test:p", path=path, reason=REASON).path == path


@pytest.mark.parametrize(
    "path",
    [
        "*",
        "entity_id",
        "players.sample",
        "players.sample[0].name",
        "l[10]",
        'json_response["a.b"]',
        '["weird key"].x',
        'm[""]',
    ],
)
def test_a_mask_takes_a_field_path_or_a_star(path: str) -> None:
    assert Mask(packet="minecraft:login", path=path, reason=REASON).path == path


@pytest.mark.parametrize("reason", ["", "  \n"])
def test_a_mask_needs_a_reason(reason: str) -> None:
    with pytest.raises(ValueError, match="minecraft:login entity_id: a Mask needs a reason"):
        Mask(packet="minecraft:login", path="entity_id", reason=reason)


def test_a_mask_needs_a_packet_name() -> None:
    with pytest.raises(ValueError, match="a Mask needs a packet name"):
        Mask(packet="", path="entity_id", reason=REASON)


@pytest.mark.parametrize(
    "path",
    [
        "",
        ".a",
        "a.",
        "a..b",
        "a b",
        "a[",
        "a[]",
        "a[01]",
        "a[-1]",
        "a[1]b",
        "[0]",
        "[0].a",
        'a["x"',
        'a["x]',
        "a[1.5]",
        "a.*",
        "**",
    ],
)
def test_a_mask_rejects_a_malformed_path(path: str) -> None:
    error = re.escape(f"minecraft:login: malformed Mask path {path!r}")
    with pytest.raises(ValueError, match=error):
        Mask(packet="minecraft:login", path=path, reason=REASON)


@pytest.mark.parametrize(
    ("path", "canonical"),
    [
        ('["abc"]', "abc"),
        ('a["b"]', "a.b"),
        ('m["\\u00e9"]', 'm["\xe9"]'),
    ],
)
def test_a_mask_path_must_be_spelled_as_divergences_spell_it(path: str, canonical: str) -> None:
    # One spelling per path, so a path copied from a Divergence is the Mask's path.
    with pytest.raises(ValueError, match=re.escape(f"write {canonical!r}")):
        Mask(packet="minecraft:login", path=path, reason=REASON)
