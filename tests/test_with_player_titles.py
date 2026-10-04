"""Every test case of a default Pumpkin Report has a title (#255)."""

import pytest

from mscts.case_titles import TITLES

UNTITLED_BEFORE = [
    "configuration:custom_payload.channel",
    "configuration:update_tags.tagged_registries[].registry",
    "login_compression.threshold",
    "login_finished.profile.username",
    "select_known_packs.known_packs[].id",
    "select_known_packs.known_packs[].namespace",
    "select_known_packs.known_packs[].version",
    "status_response.players.sample[].name",
    "update_enabled_features.feature_flags[]",
]


@pytest.mark.parametrize("name", UNTITLED_BEFORE)
def test_a_status_with_player_test_case_has_a_title(name: str) -> None:
    assert name in TITLES
