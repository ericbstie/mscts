"""Short titles for the test case reference and Report (#12)."""

from collections.abc import Mapping
from types import MappingProxyType

TITLES: Mapping[str, str] = MappingProxyType(
    {
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
    }
)
"""Known test case name → the short title checked against the docs reference."""
