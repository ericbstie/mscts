"""Schema declarations that can never be valid are rejected when defined."""

from typing import cast

import pytest

from mscts.codec.schema import SchemaError, String


# The Data types page caps String (n) at n <= 32767 UTF-16 code units.
@pytest.mark.parametrize("max_length", [32768, 0, -1])
def test_string_rejects_a_max_length_outside_1_to_32767(max_length: int) -> None:
    with pytest.raises(SchemaError, match=rf"String max_length {max_length} is not in 1\.\.32767"):
        String(max_length)


@pytest.mark.parametrize("max_length", [True, 2.5, "16", None])
def test_string_rejects_a_max_length_that_is_not_an_int(max_length: object) -> None:
    # Audit L5: String(True) and String(2.5) were accepted.
    with pytest.raises(SchemaError, match="String max_length must be an int"):
        String(cast("int", max_length))


@pytest.mark.parametrize("max_length", [1, 32767])
def test_string_accepts_a_max_length_at_the_bounds(max_length: int) -> None:
    assert String(max_length).max_length == max_length
