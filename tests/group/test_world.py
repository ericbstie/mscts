"""The clean-up of a Group's tagged entities: what Control runs, and when it returns."""

import uuid
from typing import TYPE_CHECKING, cast

import pytest

from mscts.codec.packets import Direction, Packet, State
from mscts.entities import Entity
from mscts.groups import _world
from mscts.groups._world import remove_tagged_until_gone
from tests.group.test_combat import NONE_LEFT

if TYPE_CHECKING:
    from mscts.bot import Bot

_TAG = "mscts_entities"
_PLAYER = Entity(id=1, uuid=uuid.UUID(int=1), type="minecraft:player", x=0, y=0, z=0)


def _said(text: str) -> Packet:
    return Packet(
        state=State.PLAY,
        direction=Direction.CLIENTBOUND,
        name="minecraft:system_chat",
        packet_id=0,
        payload=text.encode(),
        fields=None,
        decode_error=None,
    )


class _World:
    """Control, and a Bot beside a mob whose killed body goes after `dying` barriers.

    `@e` never matches a dying body (docs/research/2026-10-14-tagged-cleanup.md), so every
    `execute if entity` answers that none is left. `dying` None leaves the body there.
    """

    def __init__(self, dying: int | None) -> None:
        self.name = "watcher"
        self.dying = dying
        self.commands: list[str] = []
        self.syncs = 0
        self._body = Entity(id=2, uuid=uuid.UUID(int=2), type="minecraft:pig", x=1, y=0, z=0)

    @property
    def entities(self) -> dict[int, Entity]:
        """What the Bot tracks: the player, and the body until it goes."""
        tracked = {_PLAYER.id: _PLAYER}
        if self.dying is None or self.syncs < self.dying:
            tracked[self._body.id] = self._body
        return tracked

    async def run(self, command: str) -> tuple[Packet, ...]:
        self.commands.append(command)
        if command.startswith("execute if entity"):
            return (_said(NONE_LEFT),)
        return ()

    async def leave(self) -> None:
        """Nothing to close."""

    async def sync(self) -> None:
        self.syncs += 1


@pytest.mark.asyncio
async def test_the_clean_up_returns_once_the_bot_tracks_only_players() -> None:
    world = _World(dying=5)

    await remove_tagged_until_gone(world, _TAG, cast("Bot", world))

    assert world.syncs == 5
    assert f"kill @e[tag={_TAG}]" in world.commands


@pytest.mark.asyncio
async def test_the_clean_up_kills_without_drops_unfreezes_and_never_asks_with_execute() -> None:
    world = _World(dying=0)

    await remove_tagged_until_gone(world, _TAG, cast("Bot", world))

    assert world.commands == [
        "gamerule mob_drops false",
        f"kill @e[tag={_TAG}]",
        "gamerule mob_drops true",
        "tick unfreeze",
    ]


@pytest.mark.asyncio
async def test_a_body_that_never_goes_ends_the_clean_up_with_a_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_world, "_GONE_SYNCS", 3)
    world = _World(dying=None)

    with pytest.raises(TimeoutError, match="watcher still tracked an entity after 3 barriers"):
        await remove_tagged_until_gone(world, _TAG, cast("Bot", world))
    assert world.syncs == 3
