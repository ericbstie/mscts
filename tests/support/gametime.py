"""Vanilla's answer to `time query gametime`, as a fake server says it."""

GAMETIME_ANSWER = bytes.fromhex(
    "0a09000477697468040000000100000000000000380800097472616e736c617465001c"
    "636f6d6d616e64732e74696d652e71756572792e67616d6574696d650000"
)[:-1]
"""What vanilla 26.3 answered to `time query gametime` at game time 56: a system_chat's
content, recorded live, without the overlay byte that follows it."""


def gametime_answer(value: int) -> bytes:
    """Vanilla's answer to `time query gametime` at game time `value`."""
    return GAMETIME_ANSWER[:13] + value.to_bytes(8, "big") + GAMETIME_ANSWER[21:]
