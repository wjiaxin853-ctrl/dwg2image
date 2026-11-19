"""AC1015 and R2010+ HATCH payload (ODA DWG specification section 20.4.75).

The caller decodes the pattern name with the drawing code page and resolves
boundary object handles from the separate handle stream.
"""
import math

from ._native_bits import DwgFormatError


def _count(reader, minimum_bits=1, short=False):
    count = reader.short() if short else reader.long()
    if count < 0 or count > (getattr(reader, 'limit', len(reader.data) * 8) - reader.pos) // minimum_bits:
        raise DwgFormatError('HATCH array count exceeds available data')
    return count


def _xy(reader):
    return (reader.rd(), reader.rd())


def _edge(reader, r18=False):
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
        edge = dict(type='spline', degree=degree, rational=rational, periodic=periodic,
                    knot_values=knots, control_points=controls, weights=weights)
        if r18:
            edge['fit_points'] = [_xy(reader) for _ in range(_count(reader, 128))]
            if edge['fit_points']:
                edge['start_tangent'] = _xy(reader)
                edge['end_tangent'] = _xy(reader)
        return edge
    raise DwgFormatError(f'unknown HATCH edge type {kind}')


def decode_hatch(reader, *, r18=False):
    """Read HATCH data; r18 selects the R2010+ split-string object reader.

    The R2010+ gradient block is retained even when gradient fill is disabled.
    Colors retain their position, index, packed color method/RGB, and flags.
    """
    gradient = None
    if r18:
        gradient = {
            'gradient': reader.long(), 'reserved': reader.long(),
            'rotation': reader.double(), 'shift': reader.double(),
            'one_color': reader.long(), 'tint': reader.double(),
        }
        gradient['colors'] = [
            (reader.double(), reader.short(), reader.long(), reader.bits(8))
            for _ in range(_count(reader, 14))]
        gradient['name'] = reader.text()
    result = {'elevation': (0.0, 0.0, reader.double()),
              'extrusion': tuple(reader.double() for _ in range(3))}
    if r18:
        result['_gradient'] = gradient
        result['pattern_name'] = reader.text()
    else:
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
            path['edges'] = [_edge(reader, r18) for _ in range(_count(reader, 8))]
        boundary_count = reader.long()
        if boundary_count < 0:
            raise DwgFormatError('negative HATCH boundary handle count')
        counts.append(boundary_count)
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
