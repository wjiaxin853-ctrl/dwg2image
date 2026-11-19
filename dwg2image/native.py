"""Independent experimental AC1015 reader; never launches external programs.

Bit encodings are checked against ODA's published format description and
sample DWG/ODA-DXF pairs. Unimplemented modelspace types remain explicit.
"""
from collections import Counter
from dataclasses import dataclass
from bisect import bisect_left, bisect_right
import math
from pathlib import Path
import struct

from ._native_bits import BitReader, DwgFormatError, crc16, modular, resolve_handle


class UnsupportedDwgError(ValueError):
    """A valid-looking DWG requires an unimplemented version or entity."""


@dataclass
class NativeDrawing:
    entities: list[dict]
    layers: dict[int, dict]
    unsupported_modelspace: dict[str, int]
    object_count: int
    styles: dict[int, dict]
    linetypes: dict[int, dict]
    blocks: dict[int, dict]
    unsupported_blocks: dict[int, dict[str, int]]

    def modelspace(self) -> list[dict]:
        return [entity for entity in self.entities if entity['mode'] == 2]


_TYPES = {1: 'TEXT', 7: 'INSERT', 17: 'ARC', 18: 'CIRCLE', 19: 'LINE',
          27: 'POINT', 31: 'SOLID', 32: 'TRACE', 35: 'ELLIPSE', 36: 'SPLINE',
          28: '3DFACE', 33: 'SHAPE', 40: 'RAY', 41: 'XLINE', 44: 'MTEXT',
          45: 'LEADER', 47: 'MLINE', 77: 'LWPOLYLINE'}
_NAMES = {**_TYPES, 2: 'ATTRIB', 3: 'ATTDEF', 15: 'POLYLINE_2D', 16: 'POLYLINE_3D',
          20: 'DIMENSION_ORDINATE', 21: 'DIMENSION_LINEAR',
          22: 'DIMENSION_ALIGNED', 23: 'DIMENSION_ANG3PT',
          24: 'DIMENSION_ANG2LN', 25: 'DIMENSION_RADIUS', 26: 'DIMENSION_DIAMETER',
          36: 'SPLINE', 37: 'REGION', 78: 'HATCH'}
_ENTITY_TYPES = (set(range(1, 48)) - {42}) | {77, 78, 0x1F2}
_CODEPAGES = {1: 'ascii', 28: 'cp1250', 29: 'cp1251', 30: 'cp1252',
              38: 'cp932', 39: 'gbk', 40: 'cp949', 41: 'cp950'}


def _sections(data):
    if len(data) < 25:
        raise DwgFormatError('truncated DWG header')
    if data[:6] not in (b'AC1012', b'AC1014', b'AC1015'):
        raise UnsupportedDwgError(f'unimplemented DWG file signature {data[:6]!r}')
    count = struct.unpack_from('<I', data, 21)[0]
    if count > (len(data) - 25) // 9:
        raise DwgFormatError('section directory extends beyond file')
    result = {}
    for index in range(count):
        ident, offset, size = struct.unpack_from('<BII', data, 25 + 9 * index)
        if offset + size > len(data):
            raise DwgFormatError('section extends beyond file')
        if ident in result:
            raise DwgFormatError('duplicate section directory entry')
        result[ident] = (offset, size)
    return result


def _classes(data, section, encoding):
    start, size = section
    if size < 38:
        raise DwgFormatError('truncated classes section')
    length = struct.unpack_from('<I', data, start + 16)[0]
    if length > size - 38:
        raise DwgFormatError('class payload exceeds section')
    payload_end = start + 20 + length
    if crc16(data[start + 16:payload_end]) != int.from_bytes(data[payload_end:payload_end + 2], 'little'):
        raise DwgFormatError('classes CRC mismatch')
    reader = BitReader(data[start + 20:payload_end])
    result = {}
    while len(reader.data) * 8 - reader.pos > 7:
        number = reader.short()
        reader.short()  # proxy flags
        reader.text(encoding)  # application name
        reader.text(encoding)  # C++ name
        name = reader.text(encoding)
        reader.bits(1)  # proxy/zombie flag
        kind = reader.short()
        if kind not in (0x1F2, 0x1F3) or number in result:
            raise DwgFormatError('invalid DWG class declaration')
        result[number] = (name, kind == 0x1F2)
    return result


def _object_map(data, section):
    position, size = section
    end = position + size
    seen = set()
    while position + 4 <= end:
        page_size = int.from_bytes(data[position:position + 2], 'big')
        if page_size < 2 or position + page_size + 2 > end:
            raise DwgFormatError('object-map page extends beyond section')
        page_end = position + page_size
        expected = int.from_bytes(data[page_end:page_end + 2], 'big')
        if crc16(data[position:page_end]) != expected:
            raise DwgFormatError('object-map CRC mismatch')
        if page_size == 2:
            if page_end + 2 != end:
                raise DwgFormatError('trailing object-map data')
            return
        cursor = position + 2
        handle, address = 0, 0
        while cursor < page_end:
            delta, cursor = modular(data, cursor, page_end)
            offset, cursor = modular(data, cursor, page_end, signed=True)
            handle += delta
            address += offset
            if not delta or handle in seen or address < 0 or address + 2 > len(data):
                raise DwgFormatError('invalid object-map identity or address')
            seen.add(handle)
            yield handle, address
        position = page_end + 2
    raise DwgFormatError('missing object-map terminator')


def _object(data, address, expected_handle, classes):
    length = struct.unpack_from('<H', data, address)[0]
    start = address + 2
    if length & 0x8000:
        if start + 2 > len(data):
            raise DwgFormatError('truncated modular object size')
        high = struct.unpack_from('<H', data, start)[0]
        if high & 0x8000:
            raise DwgFormatError('invalid modular object size')
        length = (length & 0x7FFF) | (high << 15)
        start += 2
    end = start + length
    if end + 2 > len(data):
        raise DwgFormatError('object extends beyond file')
    if crc16(data[address:end]) != int.from_bytes(data[end:end + 2], 'little'):
        raise DwgFormatError(f'object CRC mismatch at {address:#x}')
    reader = BitReader(data[start:end])
    kind = reader.short()
    legacy = data[:6] < b'AC1015'
    if not legacy:
        endbit = int.from_bytes(reader.raw(4), 'little')
    code, handle = reader.handle()
    if code or handle != expected_handle:
        raise DwgFormatError('object header identity or bit length mismatch')
    size = reader.short()
    while size:
        if size < 0:
            raise DwgFormatError('negative extended data length')
        reader.handle()
        reader.skip(size * 8)
        size = reader.short()
    if legacy:
        if kind in _ENTITY_TYPES or classes.get(kind, ('', False))[1]:
            if reader.bits(1):
                reader.skip(int.from_bytes(reader.raw(4), 'little') * 8)
        endbit = int.from_bytes(reader.raw(4), 'little')
    if not reader.pos <= endbit <= length * 8:
        raise DwgFormatError('object data exceeds its declared bit length')
    return kind, reader, endbit


def _common(reader, legacy=False):
    if not legacy and reader.bits(1):
        reader.skip(int.from_bytes(reader.raw(4), 'little') * 8)
    mode = reader.bits(2)
    reactors = reader.long()
    if mode == 3 or reactors < 0:
        raise DwgFormatError('invalid entity mode or reactor count')
    linetype = 0 if not legacy or reader.bits(1) else 3
    no_links = reader.bits(1)
    color = reader.short()
    scale = reader.double()
    plotstyle = 0
    if not legacy:
        linetype, plotstyle = reader.bits(2), reader.bits(2)
    invisible = reader.short()
    lineweight = 28 if legacy else reader.bits(8)
    return dict(mode=mode, reactors=reactors, no_links=no_links, color=color,
                ltscale=scale, linetype=linetype, plotstyle=plotstyle,
                invisible=invisible, lineweight=lineweight)


def _handles(reader, endbit, handle, common, legacy=False):
    reader.pos = endbit
    owner = resolve_handle(reader.handle(), handle) if common['mode'] == 0 else None
    if common['reactors'] > (len(reader.data) * 8 - reader.pos) // 8:
        raise DwgFormatError('reactor count exceeds handle stream')
    for _ in range(common['reactors']):
        reader.handle()
    reader.handle()  # extension dictionary
    if legacy:
        layer = resolve_handle(reader.handle(), handle)
        linetype = resolve_handle(reader.handle(), handle) if common['linetype'] == 3 else None
    if not common['no_links']:
        reader.handle()
        reader.handle()
    if not legacy:
        layer = resolve_handle(reader.handle(), handle)
        linetype = resolve_handle(reader.handle(), handle) if common['linetype'] == 3 else None
    if common['plotstyle'] == 3:
        reader.handle()
    return owner, layer, linetype


def _geometry(kind, reader, *, legacy=False, version=b'AC1015'):
    if kind == 19 and legacy:
        result = dict(start=tuple(reader.double() for _ in range(3)),
                      end=tuple(reader.double() for _ in range(3)))
    elif kind == 19:
        zero_z = reader.bits(1)
        x = reader.rd()
        end_x = reader.dd(x)
        y = reader.rd()
        end_y = reader.dd(y)
        z = 0.0 if zero_z else reader.rd()
        end_z = 0.0 if zero_z else reader.dd(z)
        result = dict(start=(x, y, z), end=(end_x, end_y, end_z))
    elif kind in (17, 18):
        result = dict(center=tuple(reader.double() for _ in range(3)), radius=reader.double())
    elif kind == 27:
        result = dict(location=tuple(reader.double() for _ in range(3)))
    elif kind == 33:
        from ._native_entities import _shape
        return _shape(reader)
    elif kind == 28:
        if legacy:
            points = [tuple(reader.double() for _ in range(3)) for _ in range(4)]
            invisible = reader.short()
        else:
            no_flags = reader.bits(1)
            z_zero = reader.bits(1)
            x, y = reader.rd(), reader.rd()
            z = 0.0 if z_zero else reader.rd()
            points = [(x, y, z)]
            for _ in range(3):
                x, y, z = reader.dd(x), reader.dd(y), reader.dd(z)
                points.append((x, y, z))
            invisible = 0 if no_flags else reader.short()
        return {'points': points, 'invisible_edges': invisible}
    else:
        from ._native_entities import decode_entity
        return decode_entity(kind, reader, legacy=legacy, version=version)
    result['thickness'] = 0.0 if not legacy and reader.bits(1) else reader.double()
    result['extrusion'] = (0.0, 0.0, 1.0) if not legacy and reader.bits(1) else tuple(reader.double() for _ in range(3))
    if kind == 17:
        result['start_angle'] = math.degrees(reader.double())
        result['end_angle'] = math.degrees(reader.double())
    elif kind == 27:
        result['angle'] = math.degrees(reader.double())
    return result


def _layer(reader, encoding, endbit, handle, legacy=False):
    reactors = reader.long()
    name = reader.text(encoding)
    reader.bits(1)
    reader.short()  # external-reference index
    reader.bits(1)
    if legacy:
        flags = sum(reader.bits(1) << bit for bit in range(4)) | 16
    else:
        flags = reader.short()
    color = reader.short()
    if reader.pos != endbit:
        raise DwgFormatError('layer data bit length mismatch')
    reader.handle()
    for _ in range(reactors):
        reader.handle()
    reader.handle()  # extension dictionary
    reader.handle()  # external reference
    if not legacy:
        reader.handle()  # plotstyle
    linetype = resolve_handle(reader.handle(), handle)
    return dict(name=name, flags=flags, color=color, linetype_handle=linetype)


def _table_prefix(reader, encoding):
    reader.long()
    name = reader.text(encoding)
    reader.bits(1)
    reader.short()
    reader.bits(1)
    return name


def _style(reader, encoding):
    name = _table_prefix(reader, encoding)
    shape, vertical = reader.bits(1), reader.bits(1)
    height, width, oblique = reader.double(), reader.double(), reader.double()
    generation, last_height = reader.bits(8), reader.double()
    return dict(name=name, flags=shape | (vertical << 2), height=height, width=width,
                oblique=math.degrees(oblique), generation_flags=generation,
                last_height=last_height, font=reader.text(encoding),
                bigfont=reader.text(encoding))


def _linetype(reader, encoding, endbit):
    name = _table_prefix(reader, encoding)
    description = reader.text(encoding)
    length = reader.double()
    alignment, count = reader.bits(8), reader.bits(8)
    dashes, complex_pattern, dot_shapes = [], False, True
    for _ in range(count):
        dashes.append(reader.double())
        shape = reader.short()
        x, y = reader.rd(), reader.rd()
        scale, rotation = reader.double(), reader.double()
        flags = reader.short()
        complex_pattern |= bool(flags & ~1)
        dot_shapes &= (flags == 4 and shape == 0 and x == 0 and y == 0
                       and scale == 1 and rotation == 0)
    reader.skip(256 * 8)
    if reader.pos != endbit:
        raise DwgFormatError('linetype data bit length mismatch')
    return dict(name=name, description=description, length=length,
                dashes=dashes, complex=complex_pattern and not dot_shapes,
                dot_shapes=complex_pattern and dot_shapes)


def _block(reader, encoding, legacy=False):
    name = _table_prefix(reader, encoding)
    anonymous, attributes, external, overlay = [reader.bits(1) for _ in range(4)]
    if not legacy:
        reader.bits(1)  # loaded
    base_point = tuple(reader.double() for _ in range(3))
    return dict(name=name, base_point=base_point, external=bool(external or overlay),
                path=reader.text(encoding))


def _decode_text(raw: bytes, encoding: str) -> str:
    """Decode a DWG string, tolerating UTF-8 written under an ANSI code page.

    R2000-R2004 files normally use the header code page, but some producers
    write UTF-8 bytes while keeping (for example) code page 936 in the header.
    A strict UTF-8 decode is only attempted after the declared code page fails,
    so valid legacy text keeps its declared encoding.
    """
    try:
        return raw.decode(encoding)
    except UnicodeDecodeError:
        if encoding in ('ascii', 'cp1250', 'cp1251', 'cp1252'):
            raise
        return raw.decode('utf-8')


def _read_ac1015_dwg(source: str | Path) -> NativeDrawing:
    """Read AC1015 without ODA; unsupported modelspace types are reported.

    A successful read is not a declaration of complete CAD interpretation.
    No object is guessed from preview pixels or pre-existing DXF output.
    """
    data = Path(source).read_bytes()
    version = data[:6]
    legacy = version < b'AC1015'
    sections = _sections(data)
    if 1 not in sections or 2 not in sections:
        raise DwgFormatError('missing classes or object map section')
    page = struct.unpack_from('<H', data, 19)[0]
    if page not in _CODEPAGES:
        raise UnsupportedDwgError(f'unimplemented DWG text codepage {page}')
    encoding = _CODEPAGES[page]
    classes = _classes(data, sections[1], encoding)
    entities, layers, styles, linetypes, blocks = [], {}, {}, {}, {}
    mline_styles = {}
    vertices_by_handle = {}
    attributes_by_owner = {}
    unsupported = Counter()
    unsupported_blocks = {}
    count = 0
    for handle, address in _object_map(data, sections[2]):
        count += 1
        kind, reader, endbit = _object(data, address, handle, classes)
        if kind == 51:
            layers[handle] = _layer(reader, encoding, endbit, handle, legacy)
            continue
        if kind == 57:
            linetypes[handle] = _linetype(reader, encoding, endbit)
            continue
        if kind == 53:
            styles[handle] = _style(reader, encoding)
            continue
        if kind == 73:
            from ._native_entities import read_mline_style
            reader.long()  # reactor count
            mline_styles[handle] = read_mline_style(reader, lambda: reader.text(encoding))
            if reader.pos != endbit:
                raise DwgFormatError(f'MLINESTYLE {handle:X}: invalid data length')
            continue
        if kind == 49:
            blocks[handle] = _block(reader, encoding, legacy)
            continue
        if kind in (4, 5, 6):
            continue  # BLOCK/ENDBLK/SEQEND are structural markers
        if kind in (10, 11):
            common = _common(reader, legacy)
            from ._native_entities import decode_vertex2d, decode_vertex3d
            vertex = decode_vertex2d(reader) if kind == 10 else decode_vertex3d(reader)
            if reader.pos != endbit:
                raise DwgFormatError(f'vertex {handle:X}: data ends at {reader.pos}, expected {endbit}')
            owner, _, _ = _handles(reader, endbit, handle, common, legacy)
            if owner is not None:
                vertex['handle'] = handle
                vertex['owner'] = owner
                vertex['type'] = kind
                vertices_by_handle[handle] = vertex
            continue
        if kind not in _ENTITY_TYPES and not classes.get(kind, ('', False))[1]:
            continue
        common = _common(reader, legacy)
        name = _NAMES.get(kind, classes.get(kind, (f'TYPE_{kind:X}', True))[0])
        if name == 'HATCH':
            from ._native_hatch import decode_hatch
            attributes = decode_hatch(reader)
        elif kind in (2, 3):
            from ._native_entities import decode_attribute
            attributes = decode_attribute(kind, reader, encoding, version=version)
        elif name == 'HELIX':
            from ._native_entities import decode_helix
            attributes = decode_helix(reader)
        elif kind == 37:
            if legacy:
                # The R13/R14 REGION payload predates the ACIS layout decoded
                # here; report it as unsupported instead of mis-parsing it.
                attributes = None
            else:
                from ._native_entities import _region
                attributes = _region(reader, endbit)
        elif kind in (20, 21, 22, 23, 24, 25, 26):
            from ._native_dimension import decode_dimension
            attributes = decode_dimension(kind, reader, version=version)
        elif kind == 15:
            from ._native_entities import _polyline2d
            attributes = _polyline2d(reader)
        elif kind == 16:
            from ._native_entities import _polyline3d
            attributes = _polyline3d(reader)
        else:
            attributes = _geometry(kind, reader, legacy=legacy, version=version) if kind in _TYPES else None
        if attributes is None:
            if common['mode'] == 2:
                unsupported[name] += 1
            elif common['mode'] == 0:
                reader.pos = endbit
                owner = resolve_handle(reader.handle(), handle)
                unsupported_blocks.setdefault(owner, Counter())[name] += 1
            continue
        if reader.pos != endbit:
            raise DwgFormatError(f'{name} {handle:X}: entity data ends at {reader.pos}, expected {endbit}')
        owner, layer, linetype = _handles(reader, endbit, handle, common, legacy)
        if name == 'SHAPE':
            # SHAPE needs its external SHX file for the glyph; consume the
            # SHAPEFILE handle but report the missing glyph instead of emitting
            # a misleading placeholder.
            if common['mode'] == 2:
                unsupported[name] += 1
            elif common['mode'] == 0 and owner is not None:
                unsupported_blocks.setdefault(owner, Counter())[name] += 1
            reader.handle()
            continue
        if '_text_bytes' in attributes:
            raw_text = attributes.pop('_text_bytes').removesuffix(b'\x00')
            try:
                attributes['text'] = _decode_text(raw_text, encoding)
            except UnicodeDecodeError:
                raise DwgFormatError(
                    f'{name} {handle:X}: text bytes {raw_text!r} are not valid {encoding}') from None
        if name == 'HATCH':
            attributes['pattern_name'] = attributes.pop('_pattern_name_bytes').removesuffix(b'\x00').decode(encoding)
            for path, count in zip(attributes['_paths'], attributes.pop('_boundary_handle_counts')):
                path['source_handles'] = [f'{resolve_handle(reader.handle(), handle):X}' for _ in range(count)]
        if kind in (1, 2, 3, 44):
            attributes['style_handle'] = resolve_handle(reader.handle(), handle)
        elif kind == 7:
            attributes['block_handle'] = resolve_handle(reader.handle(), handle)
            if attributes.pop('_has_attribs'):
                attributes['has_attributes'] = True
        elif kind in (20, 21, 22, 23, 24, 25, 26):
            attributes['dimstyle_handle'] = resolve_handle(reader.handle(), handle)
            attributes['geometry_block_handle'] = resolve_handle(reader.handle(), handle)
        elif kind == 45:
            attributes['annotation_handle'] = resolve_handle(reader.handle(), handle)
            attributes['dimstyle_handle'] = resolve_handle(reader.handle(), handle)
        elif kind == 47:
            attributes['mline_style_handle'] = resolve_handle(reader.handle(), handle)
        elif kind in (15, 16):
            attributes['first_vertex_handle'] = resolve_handle(reader.handle(), handle)
            attributes['last_vertex_handle'] = resolve_handle(reader.handle(), handle)
            reader.handle()  # SEQEND
        if kind == 2:
            if owner is None:
                raise DwgFormatError(f'ATTRIB {handle:X}: missing INSERT owner')
            attributes_by_owner.setdefault(owner, []).append(attributes)
            continue
        entities.append(dict(type=name, handle=f'{handle:X}', owner=owner,
                             layer_handle=layer, linetype_handle=linetype, linetype_flag=common['linetype'],
                             mode=common['mode'],
                             color=common['color'], invisible=common['invisible'],
                             ltscale=common['ltscale'], lineweight=common['lineweight'],
                             attributes=attributes))
    inserts = {int(entity['handle'], 16): entity for entity in entities
               if entity['type'] == 'INSERT'}
    for owner, attribs in attributes_by_owner.items():
        if owner not in inserts or not inserts[owner]['attributes'].get('has_attributes'):
            raise DwgFormatError(f'ATTRIB owner {owner:X} is not an attributed INSERT')
        inserts[owner]['attributes']['_attribs'] = attribs
    polylines = {int(entity['handle'], 16): entity for entity in entities
                 if entity['type'] in ('POLYLINE_2D', 'POLYLINE_3D')}
    vertex_handles = sorted(vertices_by_handle)
    for polyline_handle, entity in polylines.items():
        attributes = entity['attributes']
        first = attributes.pop('first_vertex_handle')
        last = attributes.pop('last_vertex_handle')
        low, high = sorted((first, last))
        vertex_kind = 10 if entity['type'] == 'POLYLINE_2D' else 11
        first_vertex = bisect_left(vertex_handles, low)
        after_last_vertex = bisect_right(vertex_handles, high)
        vertices = [vertices_by_handle[handle]
                    for handle in vertex_handles[first_vertex:after_last_vertex]
                    if vertices_by_handle[handle]['type'] == vertex_kind]
        if first > last:
            vertices.reverse()
        if not vertices or vertices[0]['handle'] != first or vertices[-1]['handle'] != last:
            actual = (vertices[0]['handle'], vertices[-1]['handle']) if vertices else (None, None)
            raise DwgFormatError(f'2D polyline {polyline_handle:X}: expected vertex endpoints '
                                 f'{first:X}/{last:X}, found {actual}')
        if any(vertex['owner'] != polyline_handle for vertex in vertices):
            raise DwgFormatError(f'polyline {polyline_handle:X}: vertex ownership does not match')
        if entity['type'] == 'POLYLINE_2D':
            default_start = attributes['default_start_width']
            default_end = attributes['default_end_width']
            attributes['_points'] = [
                (vertex['location'][0], vertex['location'][1],
                 vertex['start_width'] or default_start,
                 vertex['end_width'] or default_end,
                 vertex['bulge'], vertex['flags'], vertex['tangent_dir'])
                for vertex in vertices
            ]
        else:
            attributes['_points'] = [vertex['location'] for vertex in vertices]
    from ._native_entities import attach_mline_styles
    attach_mline_styles(entities, mline_styles)
    return NativeDrawing(entities, layers, dict(unsupported), count, styles, linetypes, blocks,
                         {owner: dict(types) for owner, types in unsupported_blocks.items()})


def read_dwg(source: str | Path) -> NativeDrawing:
    """Read a supported DWG version without invoking a converter."""
    source = Path(source)
    with source.open('rb') as stream:
        signature = stream.read(6)
    if signature in (b'AC1018', b'AC1021', b'AC1024', b'AC1027', b'AC1032'):
        from ._native_r18_reader import read_r18_dwg
        return read_r18_dwg(source)
    return _read_ac1015_dwg(source)
