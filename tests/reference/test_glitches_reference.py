"""The glitch machines work on a live vanilla 26.3 (#42): bedrock breaks, and items duplicate.

A Self-check shows that two vanilla Instances do the same; this shows that what they do is the
glitch: bedrock and an end portal frame gone, a TNT primed and its block moved on, a rail and a
carpet dropped as items and their blocks moved on. Each glitch Group is played once on a
Reference of the test's own, since the Groups change game rules and the world, and the test
reads what the watcher was sent in the windows.
"""

from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractAsyncContextManager
from typing import cast

import pytest

import mscts.groups  # noqa: F401 - registers the shipped Groups
from mscts.codec.packets import Direction
from mscts.codec.registry_names import registry_names
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN
from mscts.group import GROUPS
from mscts.run import run_group
from mscts.runner import Instance
from mscts.target import TARGET
from mscts.transcript import Transcript

pytestmark = pytest.mark.reference

_WATCHER = "watcher"
_AIR = 0
_TNT, _RAIL, _CARPET = 3834, 7318, 14743
"""The block states of a TNT, an east-west rail and a white carpet in 26.3, as vanilla sent them
(#42's fact sheet): no block state names are committed."""

type Position = tuple[int, int, int]


def _fields(value: object) -> Mapping[str, object]:
    """`value`, which must be a decoded structure."""
    assert isinstance(value, Mapping)
    return cast("Mapping[str, object]", value)


def _ints(value: object, *keys: str) -> tuple[int, ...]:
    """The fields `keys` of the decoded structure `value`, which must be whole numbers."""
    fields = _fields(value)
    numbers = tuple(fields[key] for key in keys)
    assert all(isinstance(number, int) for number in numbers), fields
    return cast("tuple[int, ...]", numbers)


def _windows(transcript: Transcript) -> list[tuple[int, int]]:
    """When each Observation window opened and closed."""
    opens = [m.t_ns for m in transcript.marks if m.label.startswith(OBSERVE_OPEN)]
    closes = [m.t_ns for m in transcript.marks if m.label == OBSERVE_CLOSE]
    return list(zip(opens, closes, strict=True))


def _received(transcript: Transcript, name: str) -> Iterator[Mapping[str, object]]:
    """The fields of each `name` packet the watcher was sent inside a window, in order.

    Outside, the watcher is also sent the build and the clear-up.
    """
    windows = _windows(transcript)
    for event in transcript.events:
        packet = event.packet
        inside = any(opened <= event.t_ns <= closed for opened, closed in windows)
        if inside and (event.bot, packet.direction, packet.name) == (
            _WATCHER,
            Direction.CLIENTBOUND,
            name,
        ):
            yield packet.fields or {}


def _section_changes(fields: Mapping[str, object]) -> list[tuple[Position, int]]:
    """Where each block of a `section_blocks_update` is, and its state."""
    x, y, z = (16 * axis for axis in _ints(fields["section"], "x", "y", "z"))
    changes = []
    for block in cast("list[object]", fields["blocks"]):
        dx, dy, dz, state = _ints(block, "x", "y", "z", "state")
        changes.append(((x + dx, y + dy, z + dz), state))
    return changes


def _blocks(transcript: Transcript) -> dict[Position, int]:
    """Each block the watcher was told of in a window, by position: the last state it was sent.

    Each position is told of in one of the two packets only, so their order does not matter.
    """
    updated = {
        cast("Position", _ints(fields["pos"], "x", "y", "z")): _ints(fields, "block_state")[0]
        for fields in _received(transcript, "minecraft:block_update")
    }
    for fields in _received(transcript, "minecraft:section_blocks_update"):
        updated.update(_section_changes(fields))
    return updated


def _entities(transcript: Transcript, entity_type: str) -> list[tuple[float, float, float]]:
    """Where each entity of `entity_type` the watcher was told of appeared."""
    kind = registry_names(TARGET.minecraft_version, "minecraft:entity_type").index(entity_type)
    return [
        (cast("float", fields["x"]), cast("float", fields["y"]), cast("float", fields["z"]))
        for fields in _received(transcript, "minecraft:add_entity")
        if fields["type"] == kind
    ]


def _dropped(transcript: Transcript) -> set[str]:
    """The items the watcher was sent as an item entity's stack."""
    items = registry_names(TARGET.minecraft_version, "minecraft:item")
    return {
        items[_ints(_fields(entry)["value"], "item")[0]]
        for fields in _received(transcript, "minecraft:set_entity_data")
        for entry in cast("list[object]", fields["entries"])
        if _fields(entry)["serializer"] == "item_stack"
    }


async def _play(instance: Instance, group_id: str) -> Transcript:
    """Play `group_id` once on `instance`."""
    return await run_group(GROUPS[group_id], instance.endpoint, server="vanilla")


# Its own boot and stop, and three plays of about 20 s each.
@pytest.mark.timeout(300)
@pytest.mark.asyncio
async def test_the_glitch_machines_break_bedrock_and_duplicate_tnt_rails_and_carpets(
    boot_reference: Callable[..., AbstractAsyncContextManager[Instance]],
) -> None:
    async with boot_reference() as reference:
        bedrock = await _play(reference, "glitches/bedrock-breaking")
        tnt = await _play(reference, "glitches/tnt-duplication")
        rail_carpet = await _play(reference, "glitches/rail-carpet-duplication")

    broken = _blocks(bedrock)
    assert (broken[12, -53, 12], broken[12, -53, 4]) == (_AIR, _AIR)
    # The TNT was primed where it stood, and its block landed a block east.
    assert _entities(tnt, "minecraft:tnt") == [(22.5, -45.0, 8.5)]
    assert _blocks(tnt)[23, -45, 8] == _TNT
    assert len(list(_received(tnt, "minecraft:explode"))) == 1
    # The rail and the carpet each dropped as an item, and their blocks landed a block east.
    assert _dropped(rail_carpet) == {"minecraft:rail", "minecraft:white_carpet"}
    landed = _blocks(rail_carpet)
    assert (landed[7, -44, 22], landed[6, -44, 27]) == (_RAIL, _CARPET)
