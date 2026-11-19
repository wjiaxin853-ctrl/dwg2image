"""R2004/R18 physical page container used by R2018 DWG files."""
import struct
import zlib

from ._native_bits import DwgFormatError


_SIGNATURES = {b'AC1018', b'AC1021', b'AC1024', b'AC1027', b'AC1032'}
_FILE_ID = b'AcFssFcAJMB\0'
_DATA_PAGE_MAGIC = 0x4163043B
_PAGE_MAP_MAGIC = 0x41630E3B
_SECTION_MAP_MAGIC = 0x4163003B
_ADLER_MOD = 0xFFF1


def _unsupported(message):
    from .native import UnsupportedDwgError
    raise UnsupportedDwgError(message)


def _checksum(data, seed=0):
    low, high = seed & 0xFFFF, seed >> 16
    for start in range(0, len(data), 0x15B0):
        for value in data[start:start + 0x15B0]:
            low += value
            high += low
        low %= _ADLER_MOD
        high %= _ADLER_MOD
    return (high << 16) | low


def _file_header(data):
    if len(data) < 0xEC:
        raise DwgFormatError('truncated R2004 file header')
    state, decoded = 1, bytearray()
    for value in data[0x80:0xEC]:
        state = (state * 0x343FD + 0x269EC3) & 0xFFFFFFFF
        decoded.append(value ^ ((state >> 16) & 0xFF))
    if decoded[:12] != _FILE_ID or struct.unpack_from('<I', decoded, 0x10)[0] != 0x6C:
        raise DwgFormatError('invalid R2004 file header signature or length')
    expected_crc = struct.unpack_from('<I', decoded, 0x68)[0]
    decoded[0x68:0x6C] = b'\0' * 4
    if zlib.crc32(decoded) & 0xFFFFFFFF != expected_crc:
        raise DwgFormatError('R2004 file header CRC mismatch')
    struct.pack_into('<I', decoded, 0x68, expected_crc)
    return bytes(decoded)


def _decompress(data, expected_size):
    pos, output = 0, bytearray()

    def read_byte(label):
        nonlocal pos
        if pos >= len(data):
            raise DwgFormatError(f'truncated R2004 {label}')
        value = data[pos]
        pos += 1
        return value

    def literal_length():
        nonlocal pos
        value = read_byte('literal length')
        if value & 0xF0:
            pos -= 1
            return 0
        if value:
            return value + 3
        length = 0x0F
        while True:
            extra = read_byte('extended literal length')
            length += extra if extra else 0xFF
            if extra:
                return length + 3

    def long_length():
        value = read_byte('long compression length')
        if value:
            return value
        length = 0xFF
        while True:
            extra = read_byte('extended compression length')
            length += extra if extra else 0xFF
            if extra:
                return length

    def two_byte_offset():
        first = read_byte('two-byte offset')
        second = read_byte('two-byte offset')
        return (first >> 2) | (second << 6), first & 3

    initial = literal_length()
    if initial > expected_size or pos + initial > len(data):
        raise DwgFormatError('R2004 initial literal run exceeds its page')
    output.extend(data[pos:pos + initial])
    pos += initial

    while pos < len(data) and len(output) < expected_size:
        opcode = read_byte('compression opcode')
        if opcode == 0x11:
            break
        if opcode >= 0x40:
            length = (opcode >> 4) - 1
            second = read_byte('short compression opcode')
            offset = (second << 2) | ((opcode & 0x0C) >> 2)
            literals = opcode & 3
            if literals == 0:
                literals = literal_length()
        elif opcode == 0x10:
            length = long_length() + 9
            offset, literals = two_byte_offset()
            offset += 0x3FFF
            if literals == 0:
                literals = literal_length()
        elif 0x12 <= opcode <= 0x1F:
            length = (opcode & 0x0F) + 2
            offset, literals = two_byte_offset()
            offset += 0x3FFF
            if literals == 0:
                literals = literal_length()
        elif opcode == 0x20:
            length = long_length() + 0x21
            offset, literals = two_byte_offset()
            if literals == 0:
                literals = literal_length()
        elif 0x21 <= opcode <= 0x3F:
            length = opcode - 0x1E
            offset, literals = two_byte_offset()
            if literals == 0:
                literals = literal_length()
        else:
            raise DwgFormatError(f'invalid R2004 compression opcode {opcode:#x}')

        distance = offset + 1
        if length < 1 or distance > len(output) or len(output) + length > expected_size:
            raise DwgFormatError('invalid R2004 compression back-reference')
        for _ in range(length):
            output.append(output[-distance])
        if pos + literals > len(data) or len(output) + literals > expected_size:
            raise DwgFormatError('R2004 literal tail exceeds its page')
        output.extend(data[pos:pos + literals])
        pos += literals

    if len(output) != expected_size:
        raise DwgFormatError(f'R2004 page decoded to {len(output)} bytes; expected {expected_size}')
    return bytes(output)


def _system_page(data, offset, expected_magic, extent):
    if offset < 0 or extent < 20 or offset + 20 > len(data):
        raise DwgFormatError('R2004 system page exceeds file bounds')
    header = data[offset:offset + 20]
    magic, decoded_size, compressed_size, compression, expected_crc = struct.unpack('<IIIII', header)
    if (magic != expected_magic or compressed_size > extent - 20
            or offset + 20 + compressed_size > len(data)):
        raise DwgFormatError(f'invalid R2004 system page at {offset:#x}')
    payload = data[offset + 20:offset + 20 + compressed_size]
    zeroed = bytearray(header)
    zeroed[16:20] = b'\0' * 4
    actual_crc = _checksum(payload, _checksum(zeroed))
    if actual_crc != expected_crc:
        raise DwgFormatError(f'R2004 system page checksum mismatch at {offset:#x}')
    if compression != 2:
        _unsupported(f'R2004 system page compression {compression} is unsupported')
    return _decompress(payload, decoded_size)


def _section_pages(data, page_map):
    pages, gaps = {}, []
    offset, pos = 0x100, 0
    while pos < len(page_map):
        if pos + 8 > len(page_map):
            raise DwgFormatError('truncated R2004 section page map entry')
        page_id, extent = struct.unpack_from('<iI', page_map, pos)
        pos += 8
        if page_id < 0:
            if pos + 16 > len(page_map):
                raise DwgFormatError('truncated R2004 section gap tree node')
            links = struct.unpack_from('<iiii', page_map, pos)
            pos += 16
            gaps.append((page_id, offset, extent, links))
        elif page_id == 0 or page_id in pages:
            raise DwgFormatError(f'invalid or duplicate R2004 page id {page_id}')
        else:
            if extent < 20 or offset + 20 > len(data):
                raise DwgFormatError(f'R2004 page {page_id} exceeds file bounds')
            pages[page_id] = (offset, extent)
        offset += extent
    return pages, gaps, offset


def _sections_map(raw):
    if len(raw) < 20:
        raise DwgFormatError('truncated R2004 data section map')
    count, version, max_page_size, _, advertised_count = struct.unpack_from('<IIIII', raw)
    if count != advertised_count or version != 2 or max_page_size == 0:
        raise DwgFormatError('invalid R2004 data section map header')
    sections, pos, ids, names = [], 20, set(), set()
    for _ in range(count):
        if pos + 96 > len(raw):
            raise DwgFormatError('truncated R2004 section description')
        size = struct.unpack_from('<Q', raw, pos)[0]
        page_count, page_size, _, compressed, section_id, encrypted = struct.unpack_from(
            '<IIIIII', raw, pos + 8)
        name_bytes = raw[pos + 32:pos + 96].split(b'\0', 1)[0]
        name = name_bytes.decode('ascii', errors='strict')
        pos += 96
        if section_id in ids or name in names or (page_count and not page_size):
            raise DwgFormatError('duplicate or invalid R2004 section description')
        if compressed not in (1, 2):
            _unsupported(f'R2004 section compression {compressed} is unsupported')
        if encrypted:
            _unsupported(f'encrypted R2004 section {name!r} is unsupported')
        pages = []
        for _ in range(page_count):
            if pos + 16 > len(raw):
                raise DwgFormatError('truncated R2004 section page reference')
            pages.append(struct.unpack_from('<IIQ', raw, pos))
            pos += 16
        ids.add(section_id)
        names.add(name)
        sections.append({'id': section_id, 'name': name, 'size': size,
                         'page_size': page_size, 'compressed': compressed,
                         'pages': pages})
    if pos != len(raw):
        raise DwgFormatError('trailing bytes in R2004 data section map')
    return sections


def _data_page(data, pages, section, reference):
    page_id, stored_size, start = reference
    if page_id not in pages:
        raise DwgFormatError(f'R2004 section references missing page {page_id}')
    offset, extent = pages[page_id]
    if extent < 32 or offset + 32 > len(data):
        raise DwgFormatError(f'R2004 data page {page_id} exceeds file bounds')
    key = (0x4164536B ^ offset) & 0xFFFFFFFF
    header = bytearray(data[offset:offset + 32])
    for pos in range(0, 32, 4):
        struct.pack_into('<I', header, pos, struct.unpack_from('<I', header, pos)[0] ^ key)
    magic, section_id, data_size, page_extent, page_start, header_crc, data_crc = struct.unpack(
        '<IIIIQII', header)
    if (magic != _DATA_PAGE_MAGIC or section_id != section['id']
            or data_size != stored_size or page_extent != extent or page_start != start
            or data_size > extent - 32 or offset + 32 + data_size > len(data)):
        raise DwgFormatError(f'invalid R2004 data page header for page {page_id}')
    payload = data[offset + 32:offset + 32 + data_size]
    if _checksum(payload) != data_crc:
        raise DwgFormatError(f'R2004 data page checksum mismatch for page {page_id}')
    header[24:28] = b'\0' * 4
    if _checksum(header, data_crc) != header_crc:
        raise DwgFormatError(f'R2004 data page header checksum mismatch for page {page_id}')
    return payload


def read_r18_sections(data):
    """Decode R2004/R18 section pages, preserving each logical section by ID."""
    if len(data) < 6 or data[:6] not in _SIGNATURES:
        _unsupported('native R18 container requires an AC1018 or newer DWG signature')
    header = _file_header(data)
    page_map_id = struct.unpack_from('<I', header, 0x50)[0]
    page_map_offset = struct.unpack_from('<Q', header, 0x54)[0] + 0x100
    section_map_id = struct.unpack_from('<I', header, 0x5C)[0]
    expected_page_count = struct.unpack_from('<I', header, 0x40)[0]
    if page_map_offset < 0x100 or page_map_offset + 20 > len(data):
        raise DwgFormatError('R2004 page map address exceeds file bounds')
    page_map = _system_page(data, page_map_offset, _PAGE_MAP_MAGIC,
                            len(data) - page_map_offset)
    pages, _, page_map_end = _section_pages(data, page_map)
    if len(pages) != expected_page_count:
        raise DwgFormatError('R2004 section page count disagrees with file header')
    last_page_end = struct.unpack_from('<Q', header, 0x2C)[0]
    if page_map_end != last_page_end + 0x100:
        raise DwgFormatError('R2004 page map end disagrees with file header')
    if page_map_id not in pages or section_map_id not in pages:
        raise DwgFormatError('R2004 system page is absent from section page map')
    if pages[page_map_id][0] != page_map_offset:
        raise DwgFormatError('R2004 page map address disagrees with section page map')
    verified_page_map = _system_page(data, page_map_offset, _PAGE_MAP_MAGIC,
                                     pages[page_map_id][1])
    if verified_page_map != page_map:
        raise DwgFormatError('R2004 page map changed during validation')
    section_map_offset, section_map_extent = pages[section_map_id]
    section_map = _system_page(data, section_map_offset, _SECTION_MAP_MAGIC,
                               section_map_extent)
    sections = _sections_map(section_map)
    for section in sections:
        output = bytearray(section['size'])
        cursor = 0
        for reference in section['pages']:
            page_id, _, start = reference
            if start < cursor or start >= section['size']:
                raise DwgFormatError(f'overlapping or out-of-range pages in {section["name"]!r}')
            if (start - cursor) % section['page_size']:
                raise DwgFormatError(f'non-page-aligned gap in {section["name"]!r}')
            payload = _data_page(data, pages, section, reference)
            if section['compressed'] == 2:
                page_data = _decompress(payload, section['page_size'])
            else:
                if len(payload) != section['page_size']:
                    raise DwgFormatError(f'invalid uncompressed page {page_id} length')
                page_data = payload
            logical_size = min(section['page_size'], section['size'] - start)
            output[start:start + logical_size] = page_data[:logical_size]
            cursor = start + section['page_size']
        section['data'] = bytes(output)
    return {section['id']: section for section in sections}
