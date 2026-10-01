"""Every item stack vanilla 26.3 sends decodes strictly and re-encodes to the same bytes.

An operator Bot is given one stack for each data component a command can give, and richer
values of the same components (tests/support/gives.py), and decodes the `container_set_slot`
that arrives for each, with a Schema of this test's own (the Codec has none for the packet
yet). `SLOT` raises a WireError naming the component it cannot read.
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import pytest
from support.commands import OPERATOR, allow_commands
from support.gives import (
    GIVES,
    SET_SLOT,
    added_names,
    clear,
    given_slots,
    operator_bot,
    read_slots,
    stacks_of,
)
from support.wire import written

from mscts.codec.wire import WireError
from mscts.runner import Instance

type BootReference = Callable[..., AbstractAsyncContextManager[Instance]]


@pytest.mark.reference
@pytest.mark.asyncio
@pytest.mark.timeout(300)
async def test_every_stack_a_command_gives_decodes_strictly_and_re_encodes_to_the_same_bytes(
    boot_reference: BootReference, monkeypatch: pytest.MonkeyPatch
) -> None:
    allow_commands(monkeypatch)
    failures: list[str] = []
    async with (
        boot_reference(operators=(OPERATOR,)) as instance,
        operator_bot(instance, "vanilla") as (bot, transcript),
    ):
        for give in GIVES:
            payloads = await given_slots(bot, transcript, give.argument)
            await clear(bot)
            try:
                slots = read_slots(payloads)
            except WireError as error:
                failures.append(f"{give.label}: {error}")
                continue
            if [written(SET_SLOT, slot) for slot in slots] != payloads:
                failures.append(f"{give.label}: does not re-encode to the same bytes")
            stacks = stacks_of(slots)
            if len(stacks) != 1:
                failures.append(f"{give.label}: {len(stacks)} stacks arrived, not one")
                continue
            added, removed = added_names(stacks[0]), stacks[0]["components"]["removed"]
            if added != list(give.added) or removed != list(give.removed):
                failures.append(
                    f"{give.label}: added {added} and removed {removed}, "
                    f"not {list(give.added)} and {list(give.removed)}"
                )
    assert failures == []


@pytest.mark.reference
@pytest.mark.asyncio
@pytest.mark.timeout(180)
async def test_a_diamond_sword_with_sharpness_5_and_damage_3_decodes_to_those_values(
    boot_reference: BootReference, monkeypatch: pytest.MonkeyPatch
) -> None:
    allow_commands(monkeypatch)
    async with (
        boot_reference(operators=(OPERATOR,)) as instance,
        operator_bot(instance, "vanilla") as (bot, transcript),
    ):
        payloads = await given_slots(
            bot, transcript, "diamond_sword[enchantments={sharpness:5},damage=3]"
        )
    (sword,) = stacks_of(read_slots(payloads))
    values = {entry["type"]: entry["value"] for entry in sword["components"]["added"]}
    assert sword["count"] == 1
    assert values["minecraft:damage"] == 3
    (enchantment,) = values["minecraft:enchantments"]
    assert enchantment["level"] == 5
