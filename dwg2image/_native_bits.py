"""Bounded, MSB-first DWG bit stream primitives, using explicit byte order."""
import struct


class DwgFormatError(ValueError):
    """A declared DWG range or encoded value is malformed."""


class BitReader:
    def __init__(self, data: bytes, pos: int = 0):
        self.data = data
        self.pos = pos

    def bits(self, count: int) -> int:
        end = self.pos + count
        if count < 0 or self.pos < 0 or end > len(self.data) * 8:
            raise DwgFormatError("truncated DWG bit stream")
        if not count:
            return 0
        value = int.from_bytes(self.data[self.pos // 8:(end + 7) // 8], "big")
        value = (value >> ((8 - end % 8) % 8)) & ((1 << count) - 1)
        self.pos = end
        return value

    def skip(self, count: int) -> None:
        if count < 0 or self.pos + count > len(self.data) * 8:
            raise DwgFormatError("declared data extends beyond object")
        self.pos += count

    def raw(self, count: int) -> bytes:
        if count < 0 or self.pos + count * 8 > len(self.data) * 8:
            raise DwgFormatError("truncated DWG byte field")
        if self.pos % 8 == 0:
            start = self.pos // 8
            self.pos += count * 8
            return self.data[start:start + count]
        return bytes(self.bits(8) for _ in range(count))

    def short(self) -> int:
        code = self.bits(2)
        if code == 0:
            return struct.unpack("<h", self.raw(2))[0]
        return self.bits(8) if code == 1 else 0 if code == 2 else 256

    def long(self) -> int:
        code = self.bits(2)
        if code == 3:
            raise DwgFormatError("reserved bitlong code")
        if code == 0:
            return struct.unpack("<i", self.raw(4))[0]
        return self.bits(8) if code == 1 else 0

    def double(self) -> float:
        code = self.bits(2)
        if code == 3:
            raise DwgFormatError("reserved bitdouble code")
        return self.rd() if code == 0 else 1.0 if code == 1 else 0.0

    def rd(self) -> float:
        return struct.unpack("<d", self.raw(8))[0]

    def dd(self, default: float) -> float:
        code = self.bits(2)
        data = bytearray(struct.pack("<d", default))
        if code == 0:
            return default
        if code == 1:
            data[:4] = self.raw(4)
        elif code == 2:
            data[4:6] = self.raw(2)
            data[:4] = self.raw(4)
        else:
            data[:] = self.raw(8)
        return struct.unpack("<d", data)[0]

    def handle(self) -> tuple[int, int]:
        header = self.bits(8)
        size = header & 15
        if size > 8:
            raise DwgFormatError("handle exceeds 64 bits")
        return header >> 4, int.from_bytes(self.raw(size), "big")

    def text(self, encoding: str) -> str:
        size = self.short()
        if size < 0:
            raise DwgFormatError("negative text length")
        return self.raw(size).decode(encoding).removesuffix('\x00')


def resolve_handle(reference: tuple[int, int], current: int) -> int:
    code, value = reference
    if code in (0, 2, 3, 4, 5):
        return value
    if code == 6:
        return current + 1
    if code == 8:
        return current - 1
    if code == 10:
        return current + value
    if code == 12:
        return current - value
    raise DwgFormatError(f"unsupported handle reference code {code}")


def modular(data: bytes, position: int, end: int, *, signed=False) -> tuple[int, int]:
    value, shift = 0, 0
    while position < end:
        byte = data[position]
        position += 1
        if not byte & 0x80:
            value |= (byte & 0x3F if signed else byte) << shift
            return (-value if signed and byte & 0x40 else value), position
        value |= (byte & 0x7F) << shift
        shift += 7
        if shift >= 64:
            raise DwgFormatError("modular integer exceeds 64 bits")
    raise DwgFormatError("unterminated modular integer")


def crc16(data: bytes) -> int:
    crc = 0xC0C1
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    return crc
