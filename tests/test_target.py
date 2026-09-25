import dataclasses

import pytest

from mscts.target import TARGET, Target


def test_pinned_target_is_26_3_protocol_777_java_25() -> None:
    # ADR-0003; verified from version.json inside the 26.3 server jar.
    assert Target(minecraft_version="26.3", protocol_version=777, java_major=25) == TARGET


@pytest.mark.parametrize("field", [field.name for field in dataclasses.fields(Target)])
def test_target_is_frozen(field: str) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(TARGET, field, getattr(TARGET, field))


def test_target_has_slots() -> None:
    assert not hasattr(TARGET, "__dict__")
