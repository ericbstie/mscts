"""The rules every Comparison applies, whatever its Group: what differs between two vanilla joins.

Two vanilla 26.3 Instances differ in every join: `login_finished.session_id` is a UUID
vanilla draws at random (a random field, ADR-0011), and `update_tags` lists its
registries, and the tags of each, in an order that changes from one boot to the next.
Neither is a Divergence, so no Group masks them itself. The recorded payloads are of two
boots of the Reference (docs/research/2026-10-01-control.md).
"""

import dataclasses
from pathlib import Path
from typing import cast

from mscts.codec.packets import Codec, Packet, State
from mscts.compare import RANDOM_FIELDS, UNORDERED, Mask, Outcome, compare
from tests.compare.build import CLIENTBOUND, transcript

DATA = Path(__file__).resolve().parent / "data"
CODEC = Codec.load("26.3")


def recorded(boot: int, name: str, state: State) -> Packet:
    payload = (DATA / f"vanilla-26.3-boot{boot}-{name}.bin").read_bytes()
    packet_id = CODEC.packet_id(state, CLIENTBOUND, f"minecraft:{name}")
    return CODEC.decode(state, CLIENTBOUND, bytes([packet_id]) + payload)


def join(boot: int) -> tuple[Packet, Packet]:
    """The login_finished and the configuration update_tags of a recorded vanilla boot."""
    return (
        recorded(boot, "login_finished", State.LOGIN),
        recorded(boot, "update_tags", State.CONFIGURATION),
    )


def _list(value: object) -> list[dict[str, object]]:
    assert isinstance(value, list)
    return cast("list[dict[str, object]]", value)


def order(update_tags: Packet) -> list[tuple[object, list[object]]]:
    """Each registry, in the order sent, with its tag names in the order sent."""
    return [
        (registry["registry"], [tag["tag_name"] for tag in _list(registry["tags"])])
        for registry in _list((update_tags.fields or {})["tagged_registries"])
    ]


def as_maps(update_tags: Packet) -> dict[object, dict[object, object]]:
    """What the client reads it into: each registry's tags by name, each with its entries."""
    return {
        registry["registry"]: {tag["tag_name"]: tag["entries"] for tag in _list(registry["tags"])}
        for registry in _list((update_tags.fields or {})["tagged_registries"])
    }


def test_two_vanilla_joins_differ_in_the_session_id_and_the_order_of_tags() -> None:
    (login_1, tags_1), (login_2, tags_2) = join(1), join(2)

    assert (login_1.fields or {})["session_id"] != (login_2.fields or {})["session_id"]
    assert [registry for registry, _ in order(tags_1)] != [
        registry for registry, _ in order(tags_2)
    ]
    tag_orders = dict(order(tags_2))
    assert any(tags != tag_orders[registry] for registry, tags in order(tags_1))
    assert as_maps(tags_1) == as_maps(tags_2)  # the same tags, each with the same entries


def test_two_vanilla_joins_match_with_no_mask_of_the_groups_own() -> None:
    reference = transcript(*(("alice", packet) for packet in join(1)))
    candidate = transcript(*(("alice", packet) for packet in join(2)))

    verdict = compare(reference, candidate, [])

    assert verdict.outcome is Outcome.MATCH, verdict.divergences[:5]
    assert "login_finished.session_id" not in verdict.test_cases
    assert "configuration:update_tags.tagged_registries[].registry" in verdict.test_cases


def test_the_session_id_is_a_random_field_with_its_reason() -> None:
    assert dict(RANDOM_FIELDS) == {
        "minecraft:login_finished.session_id": (
            "Vanilla draws it at random when its first connection opens "
            "(ServerConnectionListener.getSessionId), and the client only reports it in its "
            "telemetry."
        )
    }


def test_a_random_field_is_not_compared_by_any_group() -> None:
    (login_1, _), (login_2, _) = join(1), join(2)
    reference = transcript(("alice", login_1))
    candidate = transcript(("alice", login_2))

    assert compare(reference, candidate, []).outcome is Outcome.MATCH
    # A Group's own Mask of the same field changes nothing.
    own = Mask("minecraft:login_finished", "session_id", reason="also drawn at random")
    assert compare(reference, candidate, [own]).outcome is Outcome.MATCH


def test_a_random_field_hides_only_itself() -> None:
    (login_1, _), (login_2, _) = join(1), join(2)
    fields = dict(login_2.fields or {})
    profile = cast("dict[str, object]", fields["profile"])
    fields["profile"] = {**profile, "username": "bob"}
    renamed = dataclasses.replace(login_2, fields=fields)

    verdict = compare(transcript(("alice", login_1)), transcript(("alice", renamed)), [])

    assert [d.path for d in verdict.divergences] == ["profile.username"], verdict.divergences


def test_update_tags_is_compared_sorted_by_name_with_its_reason() -> None:
    assert set(UNORDERED) == {"minecraft:update_tags"}
    assert "changes from one boot to the next" in UNORDERED["minecraft:update_tags"]
