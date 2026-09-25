"""Primitive wire types of the Java Edition protocol."""

import struct
import uuid
from typing import Self

_USHORT_STRUCT = struct.Struct(">H")
_LONG_STRUCT = struct.Struct(">q")
_UUID_BYTE_LENGTH = 16

_SEGMENT = 0x7F
_CONTINUE = 0x80
_VAR_INT_MAX_BYTES = 5
_INT_MASK = 0xFFFF_FFFF
_INT_SIGN = 0x8000_0000
_VAR_LONG_MAX_BYTES = 10
_LONG_MASK = 0xFFFF_FFFF_FFFF_FFFF
_LONG_SIGN = 0x8000_0000_0000_0000
_NON_BMP_THRESHOLD = 0xFFFF
_BYTES_PER_CODE_UNIT = 3


class WireError(ValueError):
    """Bytes that do not form a valid value of the expected wire type."""


def _utf16_length(text: str) -> int:
    """Count UTF-16 code units `text` would take (a scalar > U+FFFF counts as two)."""
    return sum(2 if ord(char) > _NON_BMP_THRESHOLD else 1 for char in text)


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

    def string(self, value: str, *, max_length: int) -> Self:
        """Append a String: a VarInt UTF-8 byte-length prefix, then the UTF-8 bytes.

        `max_length` (the protocol's `n`) bounds the number of UTF-16 code units
        `value` represents (a scalar value above U+FFFF counts as two).
        """
        if _utf16_length(value) > max_length:
            msg = f"string exceeds max length {max_length} UTF-16 code units"
            raise WireError(msg)
        encoded = value.encode("utf-8")
        if len(encoded) > max_length * _BYTES_PER_CODE_UNIT:
            msg = f"string exceeds max byte length {max_length * _BYTES_PER_CODE_UNIT}"
            raise WireError(msg)
        self.var_int(len(encoded))
        self._buffer.extend(encoded)
        return self

    def ushort(self, value: int) -> Self:
        """Append an unsigned 16-bit integer, big-endian."""
        try:
            self._buffer.extend(_USHORT_STRUCT.pack(value))
        except struct.error as exc:
            msg = f"ushort {value!r} out of range"
            raise WireError(msg) from exc
        return self

    def long(self, value: int) -> Self:
        """Append a signed 64-bit integer, big-endian, two's complement."""
        try:
            self._buffer.extend(_LONG_STRUCT.pack(value))
        except struct.error as exc:
            msg = f"long {value!r} out of range"
            raise WireError(msg) from exc
        return self

    def bool_(self, *, value: bool) -> Self:
        """Append a Bool: 0x01 for true, 0x00 for false."""
        self._buffer.append(0x01 if value else 0x00)
        return self

    def uuid(self, value: uuid.UUID) -> Self:
        """Append a UUID as its 128-bit big-endian byte form."""
        self._buffer.extend(value.bytes)
        return self

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

    def string(self, *, max_length: int) -> str:
        """Consume a String: a VarInt UTF-8 byte-length prefix, then the UTF-8 bytes.

        `max_length` (the protocol's `n`) bounds the number of UTF-16 code units
        the result represents (a scalar value above U+FFFF counts as two).
        """
        byte_length = self.var_int()
        max_bytes = max_length * _BYTES_PER_CODE_UNIT
        if byte_length < 0 or byte_length > max_bytes:
            msg = f"string byte length {byte_length} exceeds max {max_bytes}"
            raise WireError(msg)
        end = self._offset + byte_length
        if end > len(self._data):
            msg = "string truncated"
            raise WireError(msg)
        raw = self._data[self._offset : end]
        self._offset = end
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            msg = "string is not valid UTF-8"
            raise WireError(msg) from exc
        if _utf16_length(text) > max_length:
            msg = f"string exceeds max length {max_length} UTF-16 code units"
            raise WireError(msg)
        return text

    def ushort(self) -> int:
        """Consume an unsigned 16-bit integer, big-endian."""
        end = self._offset + _USHORT_STRUCT.size
        if end > len(self._data):
            msg = "ushort truncated"
            raise WireError(msg)
        (value,) = _USHORT_STRUCT.unpack(self._data[self._offset : end])
        self._offset = end
        return int(value)

    def long(self) -> int:
        """Consume a signed 64-bit integer, big-endian, two's complement."""
        end = self._offset + _LONG_STRUCT.size
        if end > len(self._data):
            msg = "long truncated"
            raise WireError(msg)
        (value,) = _LONG_STRUCT.unpack(self._data[self._offset : end])
        self._offset = end
        return int(value)

    def bool_(self) -> bool:
        """Consume a Bool: 0x01 is true, 0x00 is false, any other byte is invalid."""
        if self._offset >= len(self._data):
            msg = "bool truncated"
            raise WireError(msg)
        byte = self._data[self._offset]
        self._offset += 1
        if byte == 0x01:
            return True
        if byte == 0x00:
            return False
        msg = f"invalid bool byte {byte:#04x}"
        raise WireError(msg)

    def uuid(self) -> uuid.UUID:
        """Consume a UUID from its 128-bit big-endian byte form."""
        end = self._offset + _UUID_BYTE_LENGTH
        if end > len(self._data):
            msg = "uuid truncated"
            raise WireError(msg)
        value = uuid.UUID(bytes=self._data[self._offset : end])
        self._offset = end
        return value

    def expect_end(self) -> None:
        """Raise WireError unless every byte has been consumed.

        Lets a strict decoder assert it consumed its payload exactly.
        """
        remaining = len(self._data) - self._offset
        if remaining:
            msg = f"{remaining} unconsumed byte(s) remain"
            raise WireError(msg)
