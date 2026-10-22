"""Narrowing a decoded value to the type a test reads it as."""

from typing import cast


def dict_list(value: object) -> list[dict[str, object]]:
    """`value`, which must be a list of decoded structures."""
    assert isinstance(value, list)
    return cast("list[dict[str, object]]", value)
