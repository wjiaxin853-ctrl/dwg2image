"""R2010+ object records stored in R2004/R18 DWG section containers."""
from dataclasses import dataclass
import struct

from ._native_bits import BitReader, DwgFormatError, crc16, modular, resolve_handle


def _modular_short(data, position, end):
    value, shift = 0, 0
    while position + 2 <= end:
        word = struct.unpack_from('<H', data, position)[0]
        position += 2
        value |= (word & 0x7FFF) << shift
        if not word & 0x8000:
            return value, position
        shift += 15
        if shift >= 64:
            raise DwgFormatError('R2010 object size exceeds 64 bits')
    raise DwgFormatError('truncated R2010 object size')


def _object_map(data, object_size):
    if len(data) < 4:
        raise DwgFormatError('truncated R2010 object map')
    position, handle, address = 0, 0, 0
    seen_handles, seen_addresses, result = set(), set(), []
    while position + 4 <= len(data):
        page_size = int.from_bytes(data[position:position + 2], 'big')
        if page_size < 2 or position + page_size + 2 > len(data):
            raise DwgFormatError('R2010 object-map page exceeds section')
        page_end = position + page_size
        if crc16(data[position:page_end]) != int.from_bytes(data[page_end:page_end + 2], 'big'):
            raise DwgFormatError(f'R2010 object-map CRC mismatch at {position:#x}')
        if page_size == 2:
            if page_end + 2 != len(data):
                raise DwgFormatError('trailing R2010 object-map data')
            return result
        cursor = position + 2
        handle, address = 0, 0
        while cursor < page_end:
            delta, cursor = modular(data, cursor, page_end)
            offset, cursor = modular(data, cursor, page_end, signed=True)
            handle += delta
            address += offset
            if (not delta or handle in seen_handles or address < 4
                    or address in seen_addresses or address + 4 > object_size):
                raise DwgFormatError('invalid R2010 object-map identity or address')
            seen_handles.add(handle)
            seen_addresses.add(address)
            result.append((handle, address))
        position = page_end + 2
    raise DwgFormatError('missing R2010 object-map terminator')


class _BoundedReader(BitReader):
    def __init__(self, data, start=0, limit=None):
        super().__init__(data, start)
        self.limit = len(data) * 8 if limit is None else limit
        if start < 0 or self.limit < start or self.limit > len(data) * 8:
            raise DwgFormatError('invalid R2010 bit-stream range')

    def bits(self, count):
        if count < 0 or self.pos + count > self.limit:
            raise DwgFormatError('R2010 bit field exceeds its declared stream')
        return super().bits(count)

    def skip(self, count):
        if count < 0 or self.pos + count > self.limit:
            raise DwgFormatError('R2010 field exceeds its declared stream')
        self.pos += count

    def raw(self, count):
        if count < 0 or self.pos + count * 8 > self.limit:
            raise DwgFormatError('R2010 byte field exceeds its declared stream')
        return super().raw(count)


class _ObjectReader(_BoundedReader):
    def __init__(self, data, start, limit, string_reader):
        super().__init__(data, start, limit)
        self.string_reader = string_reader

    def text(self, encoding='utf-16le'):
        if self.string_reader is None:
            return ''
        length = self.string_reader.short()
        if length < 0:
            raise DwgFormatError('negative R2010 Unicode string length')
        raw = self.string_reader.raw(length * 2)
        return raw.decode('utf-16le').removesuffix('\x00')


@dataclass
class R18Object:
    handle: int
    kind: int
    offset: int
    size: int
    body: bytes
    data_reader: _ObjectReader
    handle_reader: _BoundedReader
    data_start: int
    data_end: int
    strings_present: bool
    crc_ok: bool


def _object_type(reader):
    code = reader.bits(2)
    if code == 0:
        return reader.bits(8)
    if code == 1:
        return reader.bits(8) + 0x1F0
    return reader.bits(16)


def _record(data, offset, expected_handle):
    size, position = _modular_short(data, offset, len(data))
    handle_bits, body_start = modular(data, position, len(data))
    body_end = body_start + size
    if (size < 2 or body_end + 2 > len(data)
            or handle_bits > size * 8):
        raise DwgFormatError(f'invalid R2010 object boundary at {offset:#x}')
    stored_crc = int.from_bytes(data[body_end:body_end + 2], 'little')
    if crc16(data[offset:body_end]) != stored_crc:
        raise DwgFormatError(f'R2010 object CRC mismatch at {offset:#x}')

    body = data[body_start:body_end]
    prehandle_end = size * 8 - handle_bits
    header = _BoundedReader(body, 0, prehandle_end)
    kind = _object_type(header)
    code, raw_handle = header.handle()
    own_handle = resolve_handle((code, raw_handle), expected_handle)
    if own_handle != expected_handle:
        raise DwgFormatError(f'R2010 object map handle mismatch at {offset:#x}')

    eed_size = header.short()
    while eed_size:
        if eed_size < 0:
            raise DwgFormatError(f'negative R2010 EED size at {offset:#x}')
        header.handle()
        header.skip(eed_size * 8)
        eed_size = header.short()
    data_start = header.pos

    strings_present = False
    data_end = prehandle_end - 1
    string_reader = None
    if prehandle_end > 0:
        strings_present = _BoundedReader(body, prehandle_end - 1, prehandle_end).bits(1) == 1
    if strings_present:
        if prehandle_end < 17:
            raise DwgFormatError(f'truncated R2010 string-stream trailer at {offset:#x}')
        size_reader = _BoundedReader(body, prehandle_end - 17, prehandle_end - 1)
        stream_size = int.from_bytes(size_reader.raw(2), 'little')
        trailer_bits = 17
        if stream_size & 0x8000:
            if prehandle_end < 33:
                raise DwgFormatError(f'truncated R2010 large string-stream trailer at {offset:#x}')
            high_reader = _BoundedReader(body, prehandle_end - 33, prehandle_end - 17)
            high_size = int.from_bytes(high_reader.raw(2), 'little')
            stream_size = (stream_size & 0x7FFF) | (high_size << 15)
            trailer_bits = 33
        string_end = prehandle_end - trailer_bits
        string_start = string_end - stream_size
        if string_start < data_start:
            raise DwgFormatError(f'R2010 string stream overlaps object header at {offset:#x}')
        data_end = string_start
        string_reader = _BoundedReader(body, string_start, string_end)
    elif data_end < data_start:
        raise DwgFormatError(f'R2010 object header exceeds data stream at {offset:#x}')

    handle_reader = _BoundedReader(body, prehandle_end, size * 8)
    return R18Object(
        handle=expected_handle, kind=kind, offset=offset, size=size, body=body,
        data_reader=_ObjectReader(body, data_start, data_end, string_reader),
        handle_reader=handle_reader, data_start=data_start,
        data_end=data_end, strings_present=strings_present, crc_ok=True)


def read_r18_objects(data, sections):
    """Read R2010+ object envelopes from an already decoded R18 section map."""
    if data[:6] not in (b'AC1027', b'AC1032'):
        raise DwgFormatError('R2010 object records require AC1027 or AC1032')
    by_name = {section['name']: section for section in sections.values()}
    try:
        object_data = by_name['AcDb:AcDbObjects']['data']
        handle_data = by_name['AcDb:Handles']['data']
    except KeyError as exc:
        raise DwgFormatError(f'missing R2010 section {exc.args[0]!r}') from exc
    if len(object_data) < 4 or struct.unpack_from('<I', object_data)[0] != 0x0DCA:
        raise DwgFormatError('invalid R2010 object section marker')
    records = _object_map(handle_data, len(object_data))
    result = {}
    for handle, offset in records:
        if offset in result:
            raise DwgFormatError(f'duplicate R2010 object offset {offset:#x}')
        result[offset] = _record(object_data, offset, handle)
    return records, result
