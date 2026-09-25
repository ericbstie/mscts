import dataclasses

import pytest

from mscts.spec import Difficulty, GameMode, ServerSpec, WorldPreset


def test_server_spec_defaults_match_plan() -> None:
    assert ServerSpec(port=25599) == ServerSpec(
        port=25599,
        motd="mscts",
        max_players=20,
        view_distance=2,
        simulation_distance=2,
        world=WorldPreset.FLAT,
        seed=0,
        game_mode=GameMode.SURVIVAL,
        difficulty=Difficulty.PEACEFUL,
        operators=(),
        compression_threshold=256,
    )


@pytest.mark.parametrize("field", [field.name for field in dataclasses.fields(ServerSpec)])
def test_server_spec_is_frozen(field: str) -> None:
    spec = ServerSpec(port=25599)
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(spec, field, getattr(spec, field))


def test_server_spec_has_slots() -> None:
    assert not hasattr(ServerSpec(port=25599), "__dict__")


def test_world_presets_are_only_flat_until_void_is_verified() -> None:
    assert [preset.value for preset in WorldPreset] == ["flat"]


def test_game_modes() -> None:
    assert [mode.value for mode in GameMode] == ["survival", "creative", "adventure", "spectator"]


def test_difficulties() -> None:
    assert [level.value for level in Difficulty] == ["peaceful", "easy", "normal", "hard"]
