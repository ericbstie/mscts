"""Primitive wire types of the Java Edition protocol."""

from typing import Self

_SEGMENT = 0x7F
_CONTINUE = 0x80
_VAR_INT_MAX_BYTES = 5
_INT_MASK = 0xFFFF_FFFF
_INT_SIGN = 0x8000_0000
_VAR_LONG_MAX_BYTES = 10
_LONG_MASK = 0xFFFF_FFFF_FFFF_FFFF
_LONG_SIGN = 0x8000_0000_0000_0000


class WireError(ValueError):
    """Bytes that do not form a valid value of the expected wire type."""


class Writer:
    """Appends wire-encoded values to a growing buffer."""

    def __init__(self) -> None:
        """Start with an empty buffer."""
        self._buffer = bytearray()

    def var_int(self, value: int) -> Self:
        """Append a signed 32-bit integer as a VarInt (two's complement, 7 bits per byte)."""
        remaining = value & _INT_MASK
        while True:
            segment = remaining & _SEGMENT
            remaining >>= 7
            if not remaining:
                self._buffer.append(segment)
                return self
            self._buffer.append(segment | _CONTINUE)

    def var_long(self, value: int) -> Self:
        """Append a signed 64-bit integer as a VarLong (two's complement, 7 bits per byte)."""
        remaining = value & _LONG_MASK
        while True:
            segment = remaining & _SEGMENT
            remaining >>= 7
            if not remaining:
                self._buffer.append(segment)
                return self
            self._buffer.append(segment | _CONTINUE)

    def to_bytes(self) -> bytes:
        """Return everything written so far."""
        return bytes(self._buffer)


class Reader:
    """Consumes wire-encoded values from the front of a byte string."""

    def __init__(self, data: bytes) -> None:
        """Read from the start of `data`."""
        self._data = data
        self._offset = 0

    def var_int(self) -> int:
        """Consume a VarInt and return it as a signed 32-bit integer."""
        result = 0
        for index in range(_VAR_INT_MAX_BYTES):
            if self._offset >= len(self._data):
                msg = "VarInt truncated"
                raise WireError(msg)
            byte = self._data[self._offset]
            self._offset += 1
            result |= (byte & _SEGMENT) << (7 * index)
            if not byte & _CONTINUE:
                return result - (1 << 32) if result & _INT_SIGN else result
        msg = "VarInt longer than 5 bytes"
        raise WireError(msg)

    def var_long(self) -> int:
        """Consume a VarLong and return it as a signed 64-bit integer."""
        result = 0
        for index in range(_VAR_LONG_MAX_BYTES):
            if self._offset >= len(self._data):
                msg = "VarLong truncated"
                raise WireError(msg)
            byte = self._data[self._offset]
            self._offset += 1
            result |= (byte & _SEGMENT) << (7 * index)
            if not byte & _CONTINUE:
                return result - (1 << 64) if result & _LONG_SIGN else result
        msg = "VarLong longer than 10 bytes"
        raise WireError(msg)
