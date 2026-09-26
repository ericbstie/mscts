"""Primitive wire types of the Java Edition protocol."""

import math
import struct
import uuid
from typing import Self

_BYTE_STRUCT = struct.Struct(">b")
_USHORT_STRUCT = struct.Struct(">H")
_INT_STRUCT = struct.Struct(">i")
_LONG_STRUCT = struct.Struct(">q")
_FLOAT_STRUCT = struct.Struct(">f")
_DOUBLE_STRUCT = struct.Struct(">d")
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
    """Bytes to read, or a value to write, that are not valid for the expected wire type."""


def _utf16_length(text: str) -> int:
    """Count UTF-16 code units `text` would take (a scalar > U+FFFF counts as two)."""
    return sum(2 if ord(char) > _NON_BMP_THRESHOLD else 1 for char in text)


def _encode_float(packer: struct.Struct, value: float) -> bytes:
    """Pack `value`, a float (not an int or bool), with `packer`."""
    if not isinstance(value, float):
        msg = f"expected a float, got {type(value).__name__}"
        raise WireError(msg)
    try:
        return packer.pack(value)
    except OverflowError as exc:
        msg = f"{value!r} is not exactly a Float (beyond its range)"
        raise WireError(msg) from exc


class Writer:
    """Appends wire-encoded values to a growing buffer."""

    def __init__(self) -> None:
        """Start with an empty buffer."""
        self._buffer = bytearray()

    def var_int(self, value: int) -> Self:
        """Append a signed 32-bit integer as a VarInt (two's complement, 7 bits per byte)."""
        if not -_INT_SIGN <= value < _INT_SIGN:
            msg = f"VarInt {value!r} out of range"
            raise WireError(msg)
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
        if not -_LONG_SIGN <= value < _LONG_SIGN:
            msg = f"VarLong {value!r} out of range"
            raise WireError(msg)
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
        `value` represents (a scalar value above U+FFFF counts as two). A lone
        surrogate is not a Unicode scalar value, so it has no UTF-8 form and is refused.
        """
        if _utf16_length(value) > max_length:
            msg = f"string exceeds max length {max_length} UTF-16 code units"
            raise WireError(msg)
        try:
            encoded = value.encode("utf-8")
        except UnicodeEncodeError as exc:
            msg = f"string is not valid Unicode: {exc.reason} at index {exc.start}"
            raise WireError(msg) from exc
        # No separate byte bound: UTF-8 never takes more than 3 bytes per UTF-16 code
        # unit, so the protocol's 3n-byte limit already holds (audit W9: dead code).
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

    def byte(self, value: int) -> Self:
        """Append a signed 8-bit integer."""
        return self._pack(_BYTE_STRUCT, value, "byte")

    def int_(self, value: int) -> Self:
        """Append a signed 32-bit integer, big-endian, two's complement."""
        return self._pack(_INT_STRUCT, value, "int")

    def float_(self, value: float) -> Self:
        """Append an IEEE 754 binary32, big-endian. It must hold `value` exactly.

        A value binary32 would round (0.1, or one beyond its range) is refused, so the
        bytes written always mean what the caller asked for. NaN and infinities pass.
        """
        encoded = _encode_float(_FLOAT_STRUCT, value)
        (back,) = _FLOAT_STRUCT.unpack(encoded)
        if back != value and not math.isnan(value):
            msg = f"{value!r} is not exactly a Float (binary32 holds {back!r})"
            raise WireError(msg)
        self._buffer.extend(encoded)
        return self

    def double(self, value: float) -> Self:
        """Append an IEEE 754 binary64, big-endian."""
        self._buffer.extend(_encode_float(_DOUBLE_STRUCT, value))
        return self

    def raw(self, data: bytes) -> Self:
        """Append `data` as it is."""
        self._buffer.extend(data)
        return self

    def _pack(self, packer: struct.Struct, value: int, name: str) -> Self:
        try:
            self._buffer.extend(packer.pack(value))
        except struct.error as exc:
            msg = f"{name} {value!r} out of range"
            raise WireError(msg) from exc
        return self

    def bool_(self, *, value: bool) -> Self:
        """Append a Bool: 0x01 for true, 0x00 for false. Anything but a bool is refused."""
        if not isinstance(value, bool):
            msg = f"expected a bool, got {type(value).__name__}"
            raise WireError(msg)
        self._buffer.append(0x01 if value else 0x00)
        return self

    def uuid(self, value: uuid.UUID) -> Self:
        """Append a UUID as its 128-bit big-endian byte form. Anything but a UUID is refused."""
        if not isinstance(value, uuid.UUID):
            msg = f"expected a UUID, got {type(value).__name__}"
            raise WireError(msg)
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
        """Consume a VarInt and return it as a signed 32-bit integer.

        Like vanilla's `VarInt.read`, only the low 32 bits count: the unused high bits of
        a 5th byte are dropped, not rejected.
        """
        result = 0
        for index in range(_VAR_INT_MAX_BYTES):
            if self._offset >= len(self._data):
                msg = "VarInt truncated"
                raise WireError(msg)
            byte = self._data[self._offset]
            self._offset += 1
            result |= (byte & _SEGMENT) << (7 * index)
            if not byte & _CONTINUE:
                result &= _INT_MASK
                return result - (1 << 32) if result & _INT_SIGN else result
        msg = "VarInt longer than 5 bytes"
        raise WireError(msg)

    def var_long(self) -> int:
        """Consume a VarLong and return it as a signed 64-bit integer.

        Like vanilla's `VarLong.read`, only the low 64 bits count: the unused high bits of
        a 10th byte are dropped, not rejected.
        """
        result = 0
        for index in range(_VAR_LONG_MAX_BYTES):
            if self._offset >= len(self._data):
                msg = "VarLong truncated"
                raise WireError(msg)
            byte = self._data[self._offset]
            self._offset += 1
            result |= (byte & _SEGMENT) << (7 * index)
            if not byte & _CONTINUE:
                result &= _LONG_MASK
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

    def byte(self) -> int:
        """Consume a signed 8-bit integer."""
        return int.from_bytes(self._take(_BYTE_STRUCT, "byte"), "big", signed=True)

    def int_(self) -> int:
        """Consume a signed 32-bit integer, big-endian, two's complement."""
        return int.from_bytes(self._take(_INT_STRUCT, "int"), "big", signed=True)

    def float_(self) -> float:
        """Consume an IEEE 754 binary32, big-endian."""
        (value,) = _FLOAT_STRUCT.unpack(self._take(_FLOAT_STRUCT, "float"))
        return float(value)

    def double(self) -> float:
        """Consume an IEEE 754 binary64, big-endian."""
        (value,) = _DOUBLE_STRUCT.unpack(self._take(_DOUBLE_STRUCT, "double"))
        return float(value)

    def raw(self, count: int) -> bytes:
        """Consume exactly `count` bytes, as they are."""
        end = self._offset + count
        if count < 0 or end > len(self._data):
            msg = f"{count} byte(s) truncated"
            raise WireError(msg)
        data = self._data[self._offset : end]
        self._offset = end
        return data

    def rest(self) -> bytes:
        """Consume every remaining byte, as they are."""
        return self.raw(self.remaining)

    def peek_rest(self) -> bytes:
        """Return every remaining byte without consuming any."""
        return self._data[self._offset :]

    def _take(self, layout: struct.Struct, name: str) -> bytes:
        """Consume the bytes of one value of `layout`, or raise `<name> truncated`."""
        end = self._offset + layout.size
        if end > len(self._data):
            msg = f"{name} truncated"
            raise WireError(msg)
        data = self._data[self._offset : end]
        self._offset = end
        return data

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

    @property
    def remaining(self) -> int:
        """The number of bytes not yet consumed."""
        return len(self._data) - self._offset

    def expect_end(self) -> None:
        """Raise WireError unless every byte has been consumed.

        Lets a strict decoder assert it consumed its payload exactly.
        """
        if self.remaining:
            msg = f"{self.remaining} unconsumed byte(s) remain"
            raise WireError(msg)
