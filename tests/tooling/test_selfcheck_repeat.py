"""How many times the Self-check tier plays each Group: 3, or MSCTS_SELFCHECK_REPEAT (#84)."""

import pytest
from support.selfcheck import DEFAULT_REPEAT, REPEAT_VAR, repeat_from


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
