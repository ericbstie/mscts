"""The item stack placeholder: every packet that carries one fails strictly until #19 lands."""

import pytest

from mscts.codec.item_stack import PENDING_ITEM_STACK
from mscts.codec.wire import Reader, WireError, Writer


def test_reading_an_item_stack_is_a_wire_error_that_names_the_issue() -> None:
    reader = Reader(bytes.fromhex("0137000000"))
    with pytest.raises(WireError, match=r"^item stack: needs #19$"):
        PENDING_ITEM_STACK.read(reader)
    assert reader.remaining == 5


@pytest.mark.parametrize("value", [None, {"count": 1}, b"\x01"])
def test_writing_an_item_stack_is_a_wire_error_that_names_the_issue(value: object) -> None:
    writer = Writer()
    with pytest.raises(WireError, match=r"^item stack: needs #19$"):
        PENDING_ITEM_STACK.write(writer, value)
    assert writer.to_bytes() == b""
