"""How many times the Self-check tier plays each Group: 3, or MSCTS_SELFCHECK_REPEAT (#84)."""

import pytest
from support.selfcheck import (
    DEFAULT_REPEAT,
    MIN_LIMIT_S,
    PLAY_LIMIT_S,
    REPEAT_VAR,
    SLOW_PLAY_LIMIT_S,
    repeat_from,
    time_limit_s,
)


def test_a_group_is_played_3_times_by_default() -> None:
    assert DEFAULT_REPEAT == 3
    assert repeat_from({}) == 3


def test_an_empty_variable_is_the_default() -> None:
    assert repeat_from({REPEAT_VAR: ""}) == DEFAULT_REPEAT


@pytest.mark.parametrize("text", ["1", "20", " 7 "])
def test_the_variable_sets_how_many_times(text: str) -> None:
    assert repeat_from({REPEAT_VAR: text}) == int(text)


@pytest.mark.parametrize("text", ["0", "-1", "three", "2.5", "1e3"])
def test_anything_but_a_whole_number_of_at_least_1_is_refused_naming_the_variable(
    text: str,
) -> None:
    with pytest.raises(
        ValueError, match=rf"MSCTS_SELFCHECK_REPEAT is {text!r}: it must be a whole"
    ):
        repeat_from({REPEAT_VAR: text})


def test_a_group_gets_the_default_play_limit_unless_it_is_listed() -> None:
    assert time_limit_s("blocks/clone", 20) == PLAY_LIMIT_S * 20
    assert "blocks/clone" not in SLOW_PLAY_LIMIT_S


def test_a_listed_group_gets_its_own_play_limit() -> None:
    assert time_limit_s("player/starvation", 20) == SLOW_PLAY_LIMIT_S["player/starvation"] * 20
    assert time_limit_s("player/starvation", 20) > time_limit_s("blocks/clone", 20)


@pytest.mark.parametrize(
    ("group_id", "play_s"),
    [
        ("glitches/bedrock-breaking", 75),
        ("glitches/tnt-duplication", 80),
        ("glitches/rail-carpet-duplication", 69),
    ],
)
def test_a_glitch_group_gets_twice_its_play_with_the_piston_groups_it_requires(
    group_id: str, play_s: int
) -> None:
    # A play of a glitch Group plays redstone/piston-push and redstone/sticky first, and took
    # `play_s` a play over 20 plays: the default 90 s left no room for a loaded host (#42).
    assert SLOW_PLAY_LIMIT_S[group_id] >= 2 * play_s


def test_every_listed_group_has_more_than_the_default_play_limit() -> None:
    assert all(limit > PLAY_LIMIT_S for limit in SLOW_PLAY_LIMIT_S.values())


@pytest.mark.parametrize("group_id", ["blocks/clone", "player/starvation"])
def test_the_limit_is_at_least_the_minimum_whatever_the_repeat(group_id: str) -> None:
    assert time_limit_s(group_id, 1) == MIN_LIMIT_S
    assert time_limit_s(group_id, 3) == MIN_LIMIT_S
