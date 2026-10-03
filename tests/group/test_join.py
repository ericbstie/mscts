"""The join Group: what Control sets up and undoes, and the one window around alice's join.

Every test plays the Group against a fake server and reads the Transcript for what each Bot
sent and the Marks. What a server answers is never asserted.
"""

import pytest

from mscts.bot import Bot
from mscts.codec.packets import Direction
from mscts.compare import OBSERVE_CLOSE, OBSERVE_OPEN
from mscts.group import GROUPS, GroupKind
from mscts.groups import join
from mscts.net import Endpoint, ProtocolError
from mscts.spec import ServerSpec
from mscts.test_cases import TITLES
from mscts.transcript import Transcript
from tests.group.test_blocks import BlocksServer, sent
from tests.group.test_control import playing

GROUP_ID = "join/basic"
ALICE, CONTROL = "alice", "control"
BATCH_FINISHED = "minecraft:chunk_batch_finished"
SET_UP = (
    "gamerule player_movement_check false",
    "gamerule respawn_radius 0",
    "gamerule natural_health_regeneration false",
)
UNDO = (
    "gamerule natural_health_regeneration true",
    "gamerule respawn_radius 10",
    "gamerule player_movement_check true",
)
"""What Control ends with: each setting put back, the last made first."""


@pytest.fixture(autouse=True)
def settled(monkeypatch: pytest.MonkeyPatch) -> list[Endpoint]:
    """Where the Group waited for no player to be online, instead of polling the fake."""
    endpoints: list[Endpoint] = []

    async def until_no_player_online(endpoint: Endpoint) -> None:
        endpoints.append(endpoint)

    monkeypatch.setattr(join, "until_no_player_online", until_no_player_online)
    return endpoints


async def play(server: BlocksServer | None = None) -> tuple[Transcript, BlocksServer]:
    """Play the Group against a fake server; return its Transcript and the server."""
    server = server or BlocksServer()
    transcript = Transcript(group_id=GROUP_ID, server="fake")
    async with playing(server, transcript) as context:
        await GROUPS[GROUP_ID].run(context)
    return transcript, server


def joined(server: BlocksServer) -> list[str]:
    """The players who joined, in order."""
    return [
        str((packet.fields or {})["name"])
        for packet in server.seen
        if packet.name == "minecraft:hello"
    ]


def test_it_is_exact_with_no_masks_prerequisites_or_spec() -> None:
    group = GROUPS[GROUP_ID]
    default = ServerSpec(host="127.0.0.1", port=25566)

    assert group.run is join.basic
    assert group.kind is GroupKind.EXACT
    assert (group.masks, group.requires) == ((), ())
    assert group.spec(default) == default


@pytest.mark.asyncio
async def test_control_sets_the_rules_leaves_and_puts_them_back_after_alice_joined(
    settled: list[Endpoint],
) -> None:
    transcript, server = await play()

    (opened,) = [mark for mark in transcript.marks if mark.label.startswith(OBSERVE_OPEN)]
    (closed,) = [mark for mark in transcript.marks if mark.label == OBSERVE_CLOSE]
    control = sent(transcript, CONTROL)
    assert [command for t, command in control if t < opened.t_ns] == list(SET_UP)
    assert [command for t, command in control if t > closed.t_ns] == list(UNDO)
    assert joined(server) == [CONTROL, ALICE, CONTROL], "alice joins alone"
    assert len(settled) == 1, "once Control has left, until the server says it is empty"


@pytest.mark.asyncio
async def test_alice_joins_in_one_window_that_ends_where_her_first_chunk_batch_arrived() -> None:
    transcript, _ = await play()

    (opened,) = [mark for mark in transcript.marks if mark.label.startswith(OBSERVE_OPEN)]
    (closed,) = [mark for mark in transcript.marks if mark.label == OBSERVE_CLOSE]
    assert opened.label == OBSERVE_OPEN, "every packet is compared"
    alice = [event for event in transcript.events if event.bot == ALICE]
    assert all(opened.t_ns <= event.t_ns for event in alice), "her whole join"
    (batch,) = [
        event.t_ns
        for event in alice
        if event.packet.name == BATCH_FINISHED and event.packet.direction is Direction.CLIENTBOUND
    ]
    assert closed.t_ns == batch + 1
    assert "minecraft:client_command" not in [event.packet.name for event in alice], "no barrier"


@pytest.mark.asyncio
async def test_the_join_is_timed_as_join_to_first_chunk() -> None:
    transcript, _ = await play()

    labels = [mark.label for mark in transcript.marks]
    assert labels == [
        OBSERVE_OPEN,
        "join.to_first_chunk:start",
        "join.to_first_chunk:end",
        OBSERVE_CLOSE,
    ]


@pytest.mark.asyncio
async def test_control_puts_the_rules_back_when_the_join_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_join = Bot.join

    async def failing_join(bot: Bot) -> None:
        if bot.name == ALICE:
            msg = "the server disconnected alice"
            raise ProtocolError(msg)
        await real_join(bot)

    monkeypatch.setattr(Bot, "join", failing_join)
    transcript = Transcript(group_id=GROUP_ID, server="fake")
    with pytest.raises(ProtocolError, match="disconnected alice"):
        async with playing(BlocksServer(), transcript) as context:
            await GROUPS[GROUP_ID].run(context)

    assert [command for _, command in sent(transcript, CONTROL)] == [*SET_UP, *UNDO]


SHOWN_TO_PUMPKIN = (
    "change_difficulty",
    "commands.nodes[]",
    "commands.nodes[].children[]",
    "commands.nodes[].flags",
    "commands.nodes[].name",
    "commands.nodes[].parser",
    "commands.nodes[].properties",
    "commands.nodes[].redirect_node",
    "commands.nodes[].suggestions_type",
    "configuration:custom_payload.data",
    "configuration:update_tags.tagged_registries[].tags[]",
    "configuration:update_tags.tagged_registries[].tags[].entries[]",
    "configuration:update_tags.tagged_registries[].tags[].tag_name",
    "container_set_content",
    "game_event",
    "initialize_border",
    "login.enforces_secure_chat",
    "login.is_flat",
    "login.sea_level",
    "login_finished.profile.uuid",
    "play:post_effects",
    "player_abilities",
    "player_info_update",
    "player_position",
    "recipe_book_add",
    "recipe_book_settings",
    "registry_data.entries[]",
    "registry_data.entries[].data",
    "registry_data.entries[].entry_id",
    "registry_data.registry_id",
    "server_data",
    "set_default_spawn_position",
    "set_entity_motion",
    "set_experience",
    "set_health",
    "set_held_slot",
    "ticking_state",
    "ticking_step",
    "update_advancements",
    "update_attributes",
    "update_recipes",
)
"""The untitled test cases the Pumpkin Report of `join/basic` showed (#30, nightly b8382a8a).
The others it compares are titled in an issue of their own."""


def test_the_test_cases_pumpkins_report_shows_have_titles() -> None:
    assert sorted(set(SHOWN_TO_PUMPKIN) - TITLES.keys()) == []
