"""AC1015 entity payloads, based on ODA DWG specification sections 20.4.

The caller owns common entity data, code-page decoding and trailing handles.
Readers must already be bounded to the object's data bit range.
"""
import math

from ._native_bits import DwgFormatError


def _point(reader):
    return tuple(reader.double() for _ in range(3))


def _extrusion(reader):
    return (0.0, 0.0, 1.0) if reader.bits(1) else _point(reader)


def _thickness(reader):
    return 0.0 if reader.bits(1) else reader.double()


def _text(reader):
    flags = reader.bits(8)
    elevation = 0.0 if flags & 1 else reader.rd()
    x, y = reader.rd(), reader.rd()
    align = (x, y) if flags & 2 else (reader.dd(x), reader.dd(y))
    result = {"insert": (x, y, elevation), "align_point": (*align, elevation),
              "extrusion": _extrusion(reader), "thickness": _thickness(reader)}
    result['oblique'] = 0.0 if flags & 4 else math.degrees(reader.rd())
    result['rotation'] = 0.0 if flags & 8 else math.degrees(reader.rd())
    result['height'] = reader.rd()
    result['width'] = 1.0 if flags & 16 else reader.rd()
    length = reader.short()
    if length < 0:
        raise DwgFormatError('negative TEXT byte length')
    result['_text_bytes'] = reader.raw(length)
    result['text_generation_flag'] = 0 if flags & 32 else reader.short()
    result['halign'] = 0 if flags & 64 else reader.short()
    result['valign'] = 0 if flags & 128 else reader.short()
    return result


def _lwpolyline(reader):
    flags = reader.short()
    result = {'flags': (1 if flags & 512 else 0) | (128 if flags & 128 else 0)}
    if flags & 4:
        result['const_width'] = reader.double()
    if flags & 8:
        result['elevation'] = reader.double()
    if flags & 2:
        result['thickness'] = reader.double()
    if flags & 1:
        result['extrusion'] = _point(reader)
    count = reader.long()
    bulges = reader.long() if flags & 16 else 0
    widths = reader.long() if flags & 32 else 0
    if min(count, bulges, widths) < 0 or bulges > count or widths > count:
        raise DwgFormatError('invalid LWPOLYLINE array lengths')
    # Each following point consumes at least two 2-bit default codes.
    if count > (len(reader.data) * 8 - reader.pos) // 4:
        raise DwgFormatError('LWPOLYLINE point count exceeds available data')
    points = []
    if count:
        x, y = reader.rd(), reader.rd()
        points.append([x, y, 0.0, 0.0, 0.0])
        for _ in range(count - 1):
            x, y = reader.dd(x), reader.dd(y)
            points.append([x, y, 0.0, 0.0, 0.0])
    for index in range(bulges):
        points[index][4] = reader.double()
    for index in range(widths):
        points[index][2] = reader.double()
        points[index][3] = reader.double()
    result['_points'] = [tuple(point) for point in points]
    return result


def _solid(reader):
    result = {'thickness': _thickness(reader)}
    elevation = reader.double()
    for index in range(4):
        result[f'vtx{index}'] = (reader.rd(), reader.rd(), elevation)
    result['extrusion'] = _extrusion(reader)
    return result


def _insert(reader):
    result = {'insert': _point(reader)}
    flags = reader.bits(2)
    if flags == 3:
        scale = (1.0, 1.0, 1.0)
    elif flags == 1:
        scale = (1.0, reader.dd(1.0), reader.dd(1.0))
    elif flags == 2:
        xscale = reader.rd()
        scale = (xscale, xscale, xscale)
    else:
        xscale = reader.rd()
        scale = (xscale, reader.dd(xscale), reader.dd(xscale))
    result.update(zip(('xscale', 'yscale', 'zscale'), scale))
    result['rotation'] = math.degrees(reader.double())
    result['extrusion'] = _point(reader)
    result['_has_attribs'] = bool(reader.bits(1))
    return result


def decode_entity(type_code, reader):
    """Read supported R2000-specific data, leaving trailing handles untouched.

    Reserved keys: _points carries LWPOLYLINE x/y/start-width/end-width/bulge;
    _text_bytes preserves source text bytes; _has_attribs selects INSERT tails.
    TEXT's STYLE and INSERT's BLOCK_HEADER handles follow common entity handles.
    """
    decoder = {1: _text, 7: _insert, 0x1f: _solid, 0x20: _solid,
               0x4d: _lwpolyline}.get(type_code)
    return decoder(reader) if decoder else None
