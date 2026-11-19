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
    def __init__(self, data, start, limit, string_reader, inline_encoding=None):
        super().__init__(data, start, limit)
        self.string_reader = string_reader
        self.inline_encoding = inline_encoding

    def text(self, encoding='utf-16le'):
        if self.inline_encoding is not None:
            return super().text(self.inline_encoding)
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
    r2013_plus: bool
    r2018_plus: bool
    version: bytes


def _object_type(reader):
    code = reader.bits(2)
    if code == 0:
        return reader.bits(8)
    if code == 1:
        return reader.bits(8) + 0x1F0
    return reader.bits(16)


def _string_stream(body, data_start, end):
    if end <= data_start:
        raise DwgFormatError('missing DWG string-stream flag')
    flag = _BoundedReader(body, end - 1, end).bits(1)
    if not flag:
        return end - 1, None
    size_offset = end - 17
    size = int.from_bytes(_BoundedReader(body, size_offset, end - 1).raw(2), 'little')
    if size & 0x8000:
        high = int.from_bytes(_BoundedReader(body, size_offset - 16, size_offset).raw(2), 'little')
        size = (size & 0x7FFF) | (high << 15)
        size_offset -= 16
    start = size_offset - size
    if start < data_start:
        raise DwgFormatError('DWG string stream overlaps record data')
    return start, _BoundedReader(body, start, size_offset)


def read_section_classes(data, raw, inline_encoding):
    """Read dynamic class IDs from the drawing's Classes section."""
    version = data[:6]
    if len(raw) < 38 or raw[:16] != bytes.fromhex('8da1c4b8c4a9f8c5c0dcf45fe7cfb68a'):
        raise DwgFormatError('invalid DWG classes section')
    payload_offset = 24 if version == b'AC1032' or (version >= b'AC1024' and data[11] > 3) else 20
    payload_end = payload_offset + struct.unpack_from('<I', raw, 16)[0]
    if payload_end + 18 > len(raw) or crc16(raw[16:payload_end]) != int.from_bytes(raw[payload_end:payload_end + 2], 'little'):
        raise DwgFormatError('DWG classes section CRC or length is invalid')
    header = _BoundedReader(raw, payload_offset * 8, payload_end * 8)
    strings = None
    if version >= b'AC1021':
        start = header.pos
        end = start + int.from_bytes(header.raw(4), 'little')
        if end > payload_end * 8:
            raise DwgFormatError('DWG classes stream exceeds section')
        data_end, strings = _string_stream(raw, header.pos, end)
        header.limit = data_end
    maximum = header.short()
    header.raw(2)
    header.bits(1)
    reader = _ObjectReader(raw, header.pos, header.limit, strings, inline_encoding)
    classes = {}
    for _ in range(maximum - 499):
        number = reader.short()
        reader.short()  # proxy flags
        reader.text()  # application
        reader.text()  # C++ name
        name = reader.text()
        reader.bits(1)  # proxy/zombie flag
        item_type = reader.short()
        for _ in range(5):
            reader.long()
        if number < 500 or number > maximum or number in classes or item_type not in (0x1F2, 0x1F3):
            raise DwgFormatError('invalid DWG class identity')
        classes[number] = (name, item_type == 0x1F2)
    if reader.limit - reader.pos > (7 if inline_encoding is not None else 0):
        raise DwgFormatError('unparsed DWG class data')
    if strings is not None and strings.pos != strings.limit:
        raise DwgFormatError('unparsed DWG class strings')
    return classes


def _record(data, offset, expected_handle, version, inline_encoding):
    size, position = _modular_short(data, offset, len(data))
    if version >= b'AC1024':
        handle_bits, body_start = modular(data, position, len(data))
    else:
        handle_bits, body_start = 0, position
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
    if version >= b'AC1024':
        kind = _object_type(header)
    else:
        kind = header.short()
        prehandle_end = int.from_bytes(header.raw(4), 'little')
        header = _BoundedReader(body, header.pos, prehandle_end)
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

    data_end, string_reader = (prehandle_end, None)
    if inline_encoding is None:
        data_end, string_reader = _string_stream(body, data_start, prehandle_end)

    handle_reader = _BoundedReader(body, prehandle_end, size * 8)
    return R18Object(
        handle=expected_handle, kind=kind, offset=offset, size=size, body=body,
        data_reader=_ObjectReader(body, data_start, data_end, string_reader, inline_encoding),
        handle_reader=handle_reader, data_start=data_start,
        data_end=data_end, strings_present=string_reader is not None, crc_ok=True,
        r2013_plus=version >= b'AC1027', r2018_plus=version >= b'AC1032', version=version)


def read_r18_objects(data, sections):
    """Read object envelopes from already decoded section data."""
    version = data[:6]
    if version not in (b'AC1018', b'AC1021', b'AC1024', b'AC1027', b'AC1032'):
        raise DwgFormatError(f'unsupported section-based DWG object version: {version!r}')
    inline_encoding = None
    if version == b'AC1018':
        from .native import _CODEPAGES, UnsupportedDwgError
        codepage = int.from_bytes(data[19:21], 'little')
        if codepage not in _CODEPAGES:
            raise UnsupportedDwgError(f'unimplemented DWG text codepage {codepage}')
        inline_encoding = _CODEPAGES[codepage]
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
        result[offset] = _record(object_data, offset, handle, version, inline_encoding)
    return records, result
