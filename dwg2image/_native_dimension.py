"""R2000 dimension payloads from the Open Design DWG format specification.

This module reads source facts only. Dimension style and anonymous block
references live in the separate object handle stream.
"""
import math

from ._native_bits import DwgFormatError


def _point(reader):
    return tuple(reader.double() for _ in range(3))


def decode_dimension(kind, reader):
    """Read an R2000 ordinate, linear, aligned, or diameter dimension body."""
    if kind not in (20, 21, 22, 26):
        raise DwgFormatError(f'unsupported dimension type {kind}')
    result = {
        'extrusion': _point(reader),
        'text_midpoint': (reader.rd(), reader.rd()),
        'elevation': reader.double(),
        '_flags1': reader.bits(8),
    }
    size = reader.short()
    if size < 0:
        raise DwgFormatError('negative dimension text length')
    result['_text_bytes'] = reader.raw(size)
    result.update(text_rotation=math.degrees(reader.double()),
                  horizontal_direction=math.degrees(reader.double()),
                  xscale=reader.double(), yscale=reader.double(),
                  zscale=reader.double(),
                  insert_rotation=math.degrees(reader.double()),
                  attachment_point=reader.short(),
                  line_spacing_style=reader.short(),
                  line_spacing_factor=reader.double(),
                  actual_measurement=reader.double())
    result['point12'] = (reader.rd(), reader.rd())
    if kind == 20:
        result.update(defpoint=_point(reader), defpoint2=_point(reader),
                      defpoint3=_point(reader), _flags2=reader.bits(8))
    elif kind in (21, 22):
        result.update(defpoint2=_point(reader), defpoint3=_point(reader),
                      defpoint=_point(reader),
                      ext_line_rotation=math.degrees(reader.double()))
        if kind == 21:
            result['dim_rotation'] = math.degrees(reader.double())
    else:
        result.update(defpoint2=_point(reader), defpoint=_point(reader),
                      leader_length=reader.double())
    return result
