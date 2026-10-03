"""Which of the stacks a command can give Pumpkin sends in a form `SLOT` decodes.

A record, not a requirement: the Candidate is not the Codec's authority (ADR-0001). An
operator Bot is given every stack in tests/support/gives.py, the same ones the Reference
test plays (tests/reference/test_item_stacks_reference.py), and each is sorted by what
arrives for it. When Pumpkin changes, the first test fails with the new lists to record.
"""

import contextlib
import dataclasses
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from support.gives import (
    GIVES,
    OPERATOR,
    Give,
    added_names,
    clear,
    given_slots,
    operator_bot,
    read_slots,
    stacks_of,
)
from support.leak_guard import kill_survivors

from mscts import install
from mscts.adapters.pumpkin import PumpkinAdapter
from mscts.bot import status_probe
from mscts.codec.packets import Packet
from mscts.codec.wire import WireError
from mscts.runner import Instance, free_endpoint, running
from mscts.spec import ServerSpec
from mscts.target import TARGET

pytestmark = pytest.mark.candidate

_GUARD = "MSCTS_LEAK_GUARD"

MALFORMED = frozenset(
    {
        # An NBT tag cut short (six of the seven components that go as NBT of their codec).
        "container_loot",
        "debug_stick_state",
        "intangible_projectile",
        "lock",
        "map_decorations",
        "recipes",
        # A holder or holder set in another form, or a record that ends early.
        "banner_patterns",
        "blocks_attacks",
        "blocks_attacks all",
        "break_sound",
        "direct instrument",
        "direct trim",
        "instrument",
        "pot_decorations",
        "provides_banner_patterns",
        "provides_trim_material",
        "trim",
        # A byte too many.
        "damage_resistant",
    }
)
"""Rows whose stack arrives in bytes `SLOT` does not decode (Pumpkin 26.3, as run)."""

SILENT = frozenset(
    {"brewing_fuel", "cooking_fuel", "hidden effect", "potion_contents", "removed", "waxed"}
)
"""Rows for which no stack arrives: Pumpkin does not take the command."""

DIFFERENT: dict[str, tuple[str, ...]] = dict.fromkeys(
    (
        "block_transformer",
        "compostable",
        "consume effects",
        "custom_name",
        "direct sound",
        "interact_animation",
        "jukebox_playable",
        "mob_visibility",
        "provides_pottery_pattern",
        "sign_text_back",
        "sign_text_front",
        "villager_food",
    ),
    (),
)
"""Rows whose stack arrives and decodes, with these components (none) instead of vanilla's."""


def _slashed(give: Give) -> bool:
    return any("/" in name for name in give.added)


@contextlib.asynccontextmanager
async def _pumpkin(cache_dir: Path, workdir: Path) -> AsyncIterator[Instance]:
    """A Pumpkin with the operator, leak-guarded like any process-starting test."""
    endpoint = free_endpoint()
    spec = ServerSpec(host=endpoint.host, port=endpoint.port, operators=(OPERATOR,))
    adapter = PumpkinAdapter()
    plan = adapter.prepare(install.require(adapter, TARGET, cache_dir), spec, workdir)
    token = uuid.uuid4().hex
    plan = dataclasses.replace(plan, env={**plan.env, _GUARD: token})
    try:
        async with running(
            plan, ready=status_probe(TARGET), ready_timeout=60, stop_timeout=5
        ) as instance:
            yield instance
    finally:
        leaked = kill_survivors(f"{_GUARD}={token}", within=3.0)
    assert not leaked, f"Pumpkin processes outlived the test: {leaked}"


def _classify(give: Give, payloads: list[bytes]) -> tuple[str, tuple[str, ...]]:
    """What arrived for `give`: malformed, silent, decoded or different, and the components."""
    try:
        stacks = stacks_of(read_slots(payloads))
    except WireError:
        return "malformed", ()
    if not stacks:
        return "silent", ()
    for stack in stacks:
        names = tuple(added_names(stack))
        if names != give.added or stack["components"]["removed"] != list(give.removed):
            return "different", names
    return "decoded", give.added


@pytest.mark.asyncio
@pytest.mark.timeout(300)
async def test_the_stacks_pumpkin_sends_for_a_command_decode_as_recorded(
    cache_dir: Path, tmp_path: Path
) -> None:
    outcomes: dict[str, tuple[str, tuple[str, ...]]] = {}
    async with (
        _pumpkin(cache_dir, tmp_path / "pumpkin") as instance,
        operator_bot(instance, "pumpkin") as (bot, transcript),
    ):
        for give in filter(lambda give: not _slashed(give), GIVES):
            payloads = await given_slots(bot, transcript, give.argument, wait_s=1.0)
            outcomes[give.label] = _classify(give, payloads)
            await clear(bot)

    malformed = frozenset(label for label, (kind, _) in outcomes.items() if kind == "malformed")
    silent = frozenset(label for label, (kind, _) in outcomes.items() if kind == "silent")
    different = {label: names for label, (kind, names) in outcomes.items() if kind == "different"}
    assert (malformed, silent, different) == (MALFORMED, SILENT, DIFFERENT), (
        f"to record:\nMALFORMED = {sorted(malformed)}\nSILENT = {sorted(silent)}\n"
        f"DIFFERENT = {different}"
    )


@pytest.mark.asyncio
@pytest.mark.timeout(120)
async def test_pumpkin_never_answers_a_give_of_a_component_with_a_slash_in_its_name(
    cache_dir: Path, tmp_path: Path
) -> None:
    # Its parser spins a worker thread for good (one of as many as the machine has cores, so a
    # few such commands stop the server): the rows with a slash are not played with the others.
    (give,) = (give for give in GIVES if give.label == "cushion/color")
    async with (
        _pumpkin(cache_dir, tmp_path / "pumpkin") as instance,
        operator_bot(instance, "pumpkin") as (bot, _),
    ):
        await bot.command(f"give {OPERATOR} minecraft:{give.argument}")
        with pytest.raises(TimeoutError):
            await bot.expect("minecraft:container_set_slot", timeout_s=3, where=_a_stack)


def _a_stack(packet: Packet) -> bool:
    return bool(stacks_of(read_slots([packet.payload])))
