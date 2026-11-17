"""AC1015 HATCH payload (ODA DWG specification section 20.4.75).

The caller decodes the pattern name with the drawing code page and resolves
boundary object handles from the separate handle stream.
"""
import math

from ._native_bits import DwgFormatError


def _count(reader, minimum_bits=1, short=False):
    count = reader.short() if short else reader.long()
    if count < 0 or count > (len(reader.data) * 8 - reader.pos) // minimum_bits:
        raise DwgFormatError('HATCH array count exceeds available data')
    return count


def _xy(reader):
    return (reader.rd(), reader.rd())


def _edge(reader):
    kind = reader.bits(8)
    if kind == 1:
        return dict(type='line', start=_xy(reader), end=_xy(reader))
    if kind in (2, 3):
        edge = dict(type='arc' if kind == 2 else 'ellipse', center=_xy(reader))
        if kind == 3:
            edge['major_axis'] = _xy(reader)
        edge['radius' if kind == 2 else 'ratio'] = reader.double()
        edge['start_angle'] = math.degrees(reader.double())
        edge['end_angle'] = math.degrees(reader.double())
        edge['ccw'] = bool(reader.bits(1))
        return edge
    if kind == 4:
        degree = reader.long()
        if degree < 1:
            raise DwgFormatError('invalid HATCH spline degree')
        rational, periodic = bool(reader.bits(1)), bool(reader.bits(1))
        knot_count = _count(reader, 2)
        control_count = _count(reader, 128)
        knots = [reader.double() for _ in range(knot_count)]
        controls, weights = [], []
        for _ in range(control_count):
            controls.append(_xy(reader))
            if rational:
                weights.append(reader.double())
        return dict(type='spline', degree=degree, rational=rational, periodic=periodic,
                    knot_values=knots, control_points=controls, weights=weights)
    raise DwgFormatError(f'unknown HATCH edge type {kind}')


def decode_hatch(reader):
    """Read an R2000 HATCH payload, preserving paths and definition lines."""
    result = {'elevation': (0.0, 0.0, reader.double()),
              'extrusion': tuple(reader.double() for _ in range(3))}
    result['_pattern_name_bytes'] = reader.raw(_count(reader, 8, short=True))
    result['solid_fill'] = reader.bits(1)
    result['associative'] = reader.bits(1)
    paths, counts = [], []
    for _ in range(_count(reader, 6)):
        flags = reader.long()
        if flags < 0:
            raise DwgFormatError('negative HATCH path flags')
        path = {'flags': flags}
        if flags & 2:
            bulges = reader.bits(1)
            path['closed'] = bool(reader.bits(1))
            vertices = []
            for _ in range(_count(reader, 128)):
                xy = _xy(reader)
                vertices.append((*xy, reader.double() if bulges else 0.0))
            path['vertices'] = vertices
        else:
            path['edges'] = [_edge(reader) for _ in range(_count(reader, 8))]
        counts.append(_count(reader, 8))
        paths.append(path)
    result['_paths'] = paths
    result['_boundary_handle_counts'] = counts
    result['hatch_style'] = reader.short()
    result['pattern_type'] = reader.short()
    lines = []
    if not result['solid_fill']:
        result['pattern_angle'] = math.degrees(reader.double())
        result['pattern_scale'] = reader.double()
        result['pattern_double'] = reader.bits(1)
        for _ in range(_count(reader, 12, short=True)):
            angle = math.degrees(reader.double())
            base = (reader.double(), reader.double())
            offset = (reader.double(), reader.double())
            dashes = [reader.double() for _ in range(_count(reader, 2, short=True))]
            lines.append((angle, base, offset, dashes))
    result['_pattern_lines'] = lines
    if any(path['flags'] & 4 for path in paths):
        result['pixel_size'] = reader.double()
    result['_seeds'] = [_xy(reader) for _ in range(_count(reader, 128))]
    return result
