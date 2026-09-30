"""The item stack field, until #19 adds `SLOT` (`codec/items.py`).

An item stack is a count, an item id and data components with no length prefix, so it
cannot be skipped without knowing every component. Until #19, a packet that carries one
is refused whole: an undecodable frame is evidence of the gap, never a silent misread.
When #19 lands, `PENDING_ITEM_STACK` is replaced by `SLOT` where it is used and this
module is deleted.
"""

from typing import NoReturn

from mscts.codec.wire import Reader, WireError, Writer

_NEEDS_SLOT = "item stack: needs #19"


class _PendingItemStack:
    def read(self, reader: Reader) -> NoReturn:
        del reader
        raise WireError(_NEEDS_SLOT)

    def write(self, writer: Writer, value: object) -> NoReturn:
        del writer, value
        raise WireError(_NEEDS_SLOT)


PENDING_ITEM_STACK = _PendingItemStack()
"""An item stack field: reading or writing one is a `WireError` ("item stack: needs #19")."""
