"""The guide's statistical Group passes its Self-check on servers that keep players (#24).

Each fake server spawns a player it has never seen at a random place and keeps that
place for the name, as vanilla keeps a player's saved position. A Group that joined the
same name in every play would then sample one place 50 times on each server.
"""

import random
import re
from collections.abc import Mapping
from pathlib import Path

import pytest

import mscts.group as groups
from mscts.codec.packets import Codec
from mscts.group import Group
from mscts.net import Endpoint
from mscts.run import run_group
from mscts.stats import PERMUTATION_SEED, SampleLog, Series, decide
from mscts.target import TARGET
from tests.net.fakes import SPAWN, JoinScript, join_server, serve

GUIDE = Path(__file__).resolve().parents[2] / "docs" / "guide" / "writing-a-group.md"
CODEC = Codec.for_target(TARGET)
_FRESH_NAME = 'context.bot(context.player_name("spawn"))'


def _example() -> str:
    """The guide's statistical Group example, as written."""
    blocks = re.finditer(r"```python\n(.*?)```", GUIDE.read_text(), flags=re.DOTALL)
    [example] = [block[1] for block in blocks if "kind=GroupKind.STATISTICAL" in block[1]]
    return str(example)


def _registered(code: str, monkeypatch: pytest.MonkeyPatch) -> Group:
    """The one Group `code` registers, in a registry of its own."""
    monkeypatch.setattr(groups, "_REGISTERED", {})
    exec(compile(code, str(GUIDE), "exec"), {"__name__": __name__})  # noqa: S102 - guide code
    [group] = groups._REGISTERED.values()  # noqa: SLF001 - what the example registered
    return group


def _keeping_players(seed: int) -> JoinScript:
    """A join that spawns a new name anywhere within 10 blocks, and an old one where it was."""
    rng = random.Random(seed)
    kept: dict[str, Mapping[str, float]] = {}

    def spawn(name: str) -> Mapping[str, float]:
        if name not in kept:
            kept[name] = {**SPAWN, "x": rng.uniform(-10, 10), "z": rng.uniform(-10, 10)}
        return kept[name]

    return JoinScript(spawn=spawn)


async def _sampled(group: Group, endpoint: Endpoint) -> Mapping[str, Series]:
    """What `group` records over its `runs` plays at `endpoint`, as the runner plays them."""
    samples = SampleLog()
    for _ in range(group.runs):
        samples.new_play()
        await run_group(group, endpoint, server="vanilla", samples=samples)
    return samples.series()


async def _self_check(group: Group) -> bool:
    """Whether `group` rejects any name, vanilla against vanilla, on two fake servers."""
    async with (
        serve(CODEC, join_server([], _keeping_players(seed=1))) as reference,
        serve(CODEC, join_server([], _keeping_players(seed=2))) as candidate,
    ):
        sides = (await _sampled(group, reference), await _sampled(group, candidate))
        decisions = decide(*sides, rng=random.Random(PERMUTATION_SEED))
    return any(decision.rejected for decision in decisions)


@pytest.mark.asyncio
async def test_the_guide_s_statistical_example_passes_its_self_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert not await _self_check(_registered(_example(), monkeypatch))


@pytest.mark.asyncio
async def test_the_example_with_one_player_name_fails_its_self_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    example = _example()
    assert _FRESH_NAME in example
    fixed = example.replace(_FRESH_NAME, 'context.bot("spawn")')

    assert await _self_check(_registered(fixed, monkeypatch))
