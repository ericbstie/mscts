import dataclasses
from typing import cast

import pytest

from mscts.spec import Difficulty, GameMode, ServerSpec, WorldPreset

HOST = "127.1.2.3"


def test_server_spec_defaults_match_plan() -> None:
    assert ServerSpec(host=HOST, port=25599) == ServerSpec(
        host=HOST,
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


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.2", HOST, "127.255.255.254"])
def test_server_spec_host_is_any_host_address_of_127_0_0_0_8(host: str) -> None:
    assert ServerSpec(host=host, port=25599).host == host


@pytest.mark.parametrize(
    "host",
    [
        "0.0.0.0",  # every interface  # noqa: S104 - the value under test, never bound
        "10.0.0.1",
        "128.0.0.1",
        "126.255.255.255",
        "127.0.0.0",  # the network address of 127.0.0.0/8
        "127.255.255.255",  # its broadcast address: connecting fails, "Network is unreachable"
        "::1",
        "::ffff:127.0.0.1",
        "localhost",  # a name, which could resolve to anything (::1 first, on some hosts)
        "127.1",  # inet_aton's short form: not what the server config would say
        " 127.0.0.1",
        "",
        2130706433,  # 127.0.0.1 as an int
    ],
)
def test_server_spec_refuses_a_host_that_is_no_loopback_host_address(host: object) -> None:
    with pytest.raises(ValueError, match=r"ServerSpec\.host="):
        ServerSpec(host=cast("str", host), port=25599)  # not always a str: that is the test


def test_server_spec_host_is_checked_on_replace_too() -> None:
    with pytest.raises(ValueError, match=r"ServerSpec\.host="):
        dataclasses.replace(ServerSpec(host=HOST, port=25599), host="192.168.1.1")


@pytest.mark.parametrize("field", [field.name for field in dataclasses.fields(ServerSpec)])
def test_server_spec_is_frozen(field: str) -> None:
    spec = ServerSpec(host=HOST, port=25599)
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(spec, field, getattr(spec, field))


def test_server_spec_has_slots() -> None:
    assert not hasattr(ServerSpec(host=HOST, port=25599), "__dict__")


def test_world_presets_are_only_flat_until_void_is_verified() -> None:
    assert [preset.value for preset in WorldPreset] == ["flat"]


def test_game_modes() -> None:
    assert [mode.value for mode in GameMode] == ["survival", "creative", "adventure", "spectator"]


def test_difficulties() -> None:
    assert [level.value for level in Difficulty] == ["peaceful", "easy", "normal", "hard"]
