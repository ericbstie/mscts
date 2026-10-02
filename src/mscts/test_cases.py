"""Short titles for the test case reference and Report (#12)."""

from collections.abc import Mapping
from types import MappingProxyType

TITLES: Mapping[str, str] = MappingProxyType(
    {
        "add_entity": "Entity appearing",
        "block_entity_data": "Block entity data",
        "block_update": "Single block change",
        "block_update.block_state": "Single block change state",
        "block_update.pos.x": "Single block change x",
        "block_update.pos.y": "Single block change y",
        "block_update.pos.z": "Single block change z",
        "level_event": "World event",
        "level_event.event_id": "World event type",
        "section_blocks_update": "Block changes in a section",
        "section_blocks_update.blocks[]": "Block change in a section",
        "section_blocks_update.blocks[].state": "Block state in a section change",
        "section_blocks_update.blocks[].x": "Block x in a section change",
        "section_blocks_update.blocks[].y": "Block y in a section change",
        "section_blocks_update.blocks[].z": "Block z in a section change",
        "section_blocks_update.section.y": "Section height",
        "set_entity_data": "Entity data",
        "status_response.description": "Server list description",
        "status_response.description.text": "Server list description text",
        "status_response.enforceSecureChat": "Unused secure chat flag",
        "status_response.favicon": "Server list icon",
        "status_response.players.max": "Player limit",
        "status_response.players.online": "Online players",
        "status_response.players.sample": "Server list player sample",
        "status_response.version.name": "Server version name",
        "status_response.version.protocol": "Protocol version",
        "status:pong_response.timestamp": "Server list ping response",
        "system_chat": "Chat message from the server",
        "system_chat.content": "Chat message text",
    }
)
"""Known test case name → the short title checked against the docs reference."""
