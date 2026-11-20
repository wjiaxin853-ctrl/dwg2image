"""AC1015 entity payloads, based on ODA DWG specification sections 20.4.

The caller owns common entity data, code-page decoding and trailing handles.
Readers must already be bounded to the object's data bit range.
"""
import math
import struct

from ._native_bits import DwgFormatError


def _point(reader):
    return tuple(reader.double() for _ in range(3))


def _extrusion(reader):
    return (0.0, 0.0, 1.0) if reader.bits(1) else _point(reader)


def _thickness(reader):
    return 0.0 if reader.bits(1) else reader.double()


def _text_value(reader, *, split_string=False):
    if split_string:
        return reader.text().encode('utf-8')
    length = reader.short()
    if length < 0:
        raise DwgFormatError('negative TEXT byte length')
    return reader.raw(length)


def _text(reader, *, split_string=False, legacy=False):
    if legacy:
        # R13/R14 (AC1012/AC1014): no DataFlags byte and no default-value
        # bitcodes; every field is present.  See ODA DWG specification 20.4.3.
        elevation = reader.double()
        x, y = reader.rd(), reader.rd()
        ax, ay = reader.rd(), reader.rd()
        result = {"insert": (x, y, elevation), "align_point": (ax, ay, elevation),
                  "extrusion": _point(reader), "thickness": reader.double()}
        result['oblique'] = math.degrees(reader.double())
        result['rotation'] = math.degrees(reader.double())
        result['height'] = reader.double()
        result['width'] = reader.double()
        result['_text_bytes'] = _text_value(reader, split_string=split_string)
        result['text_generation_flag'] = reader.short()
        result['halign'] = reader.short()
        result['valign'] = reader.short()
        return result
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
    result['_text_bytes'] = _text_value(reader, split_string=split_string)
    result['text_generation_flag'] = 0 if flags & 32 else reader.short()
    result['halign'] = 0 if flags & 64 else reader.short()
    result['valign'] = 0 if flags & 128 else reader.short()
    return result


def decode_attribute(type_code, reader, encoding, *, split_string=False, version=b'AC1015'):
    result = _text(reader, split_string=split_string, legacy=version < b'AC1015')
    if version >= b'AC1024':
        reader.bits(8)  # attribute record version
    if version >= b'AC1032' and reader.bits(8) not in (0, 1):
        raise DwgFormatError('embedded multiline ATTRIB or ATTDEF is unsupported')
    result.update(tag=reader.text(encoding), field_length=reader.short(),
                  flags=reader.bits(8))
    if version >= b'AC1021':
        result['lock_position'] = reader.bits(1)
    if type_code == 3:
        if version >= b'AC1024':
            reader.bits(8)  # attribute definition version
        result['prompt'] = reader.text(encoding)
    return result


def _lwpolyline(reader, *, vertex_ids_present=False, legacy=False):
    flags = reader.short()
    result = {'flags': (1 if flags & 512 else 0) | (128 if flags & 256 else 0)}
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
    ids = reader.long() if vertex_ids_present and flags & 1024 else 0
    widths = reader.long() if flags & 32 else 0
    if min(count, bulges, ids, widths) < 0 or max(bulges, ids, widths) > count:
        raise DwgFormatError('invalid LWPOLYLINE array lengths')
    # Each following point consumes at least two 2-bit default codes.
    if count > (len(reader.data) * 8 - reader.pos) // 4:
        raise DwgFormatError('LWPOLYLINE point count exceeds available data')
    points = []
    if count:
        if legacy:
            # R13/R14 store every vertex as two raw doubles.
            points = [[reader.rd(), reader.rd(), 0.0, 0.0, 0.0] for _ in range(count)]
        else:
            x, y = reader.rd(), reader.rd()
            points.append([x, y, 0.0, 0.0, 0.0])
            for _ in range(count - 1):
                x, y = reader.dd(x), reader.dd(y)
                points.append([x, y, 0.0, 0.0, 0.0])
    for index in range(bulges):
        points[index][4] = reader.double()
    if ids:
        result['_vertex_ids'] = [reader.long() for _ in range(ids)]
    for index in range(widths):
        points[index][2] = reader.double()
        points[index][3] = reader.double()
    result['_points'] = [tuple(point) for point in points]
    return result


def _polyline2d(reader, *, r18=False, legacy=False):
    flags, curve_type = reader.short(), reader.short()
    start_width, end_width = reader.double(), reader.double()
    result = {'flags': flags, 'curve_type': curve_type,
              'default_start_width': start_width,
              'default_end_width': end_width,
              'thickness': reader.double() if legacy else _thickness(reader),
              'elevation': reader.double(),
              'extrusion': _point(reader) if legacy else _extrusion(reader),
              'first_vertex_handle': None, 'last_vertex_handle': None}
    if r18:
        result['owned_count'] = reader.long()
    return result


def decode_vertex2d(reader, *, r18=False):
    """Read one R2000 VERTEX_2D body; the parent POLYLINE supplies z/thickness."""
    flags = reader.bits(8)
    location = _point(reader)
    start_width = reader.double()
    if start_width < 0:
        start_width = abs(start_width)
        end_width = start_width
    else:
        end_width = reader.double()
    bulge = reader.double()
    vertex_id = reader.long() if r18 else None
    result = {'flags': flags, 'location': location,
            'start_width': start_width, 'end_width': end_width,
            'bulge': bulge, 'tangent_dir': reader.double()}
    if r18:
        result['vertex_id'] = vertex_id
    return result


def _polyline3d(reader, *, r18=False):
    curve_flags, flags = reader.bits(8), reader.bits(8)
    smooth_type = 5 if curve_flags & 1 else 6 if curve_flags & 2 else 0
    result = {'flags': 8 | (1 if flags & 1 else 0) | (4 if smooth_type else 0),
              'smooth_type': smooth_type}
    if r18:
        result['owned_count'] = reader.long()
    return result


def decode_vertex3d(reader):
    return {'flags': reader.bits(8), 'location': _point(reader)}


def _spline(reader, *, r18=False):
    from ._native_bits import DwgFormatError

    scenario = reader.long()
    if r18:
        spline_flags = reader.long()
        reader.long()  # R2013+ knot parameter
        if spline_flags & 1:
            scenario = 2  # R2013+ fit-point flag selects the fit-point payload
    degree = reader.long()

    def points(count, label):
        if count < 0 or count > (len(reader.data) * 8 - reader.pos) // 6:
            raise DwgFormatError(f'invalid SPLINE {label} count')
        return [_point(reader) for _ in range(count)]

    if scenario == 2:
        result = {'scenario': scenario, 'degree': degree,
                  'fit_tolerance': reader.double(),
                  'start_tangent': _point(reader), 'end_tangent': _point(reader)}
        count = reader.long()
        result['_fit_points'] = points(count, 'fit point')
        return result
    if scenario != 1:
        raise DwgFormatError(f'unsupported SPLINE scenario {scenario}')

    rational, closed, periodic = (reader.bits(1) for _ in range(3))
    knot_tolerance, control_tolerance = reader.double(), reader.double()
    knot_count, control_count = reader.long(), reader.long()
    has_weights = reader.bits(1)
    if knot_count < 0 or knot_count > (len(reader.data) * 8 - reader.pos) // 2:
        raise DwgFormatError('invalid SPLINE knot count')
    knots = [reader.double() for _ in range(knot_count)]
    control_points, weights = [], []
    for _ in range(control_count):
        control_points.append(_point(reader))
        if has_weights:
            weights.append(reader.double())
    return {'scenario': scenario, 'degree': degree,
            'rational': bool(rational), 'closed': bool(closed), 'periodic': bool(periodic),
            'knot_tolerance': knot_tolerance, 'control_tolerance': control_tolerance,
            'knots': knots, '_control_points': control_points, '_weights': weights}


def _leader(reader, *, r18=False, version=b'AC1015'):
    reader.bits(1)  # reserved
    annotation_type, path_type = reader.short(), reader.short()
    count = reader.long()
    if count < 0 or count > (len(reader.data) * 8 - reader.pos) // 6:
        raise DwgFormatError('invalid LEADER vertex count')
    # ODA specification 20.4.47: vertices, origin, extrusion, x direction and
    # offset to block insertion point; endpoint projection exists since R14,
    # R13 stores DIMGAP instead.
    result = {'annotation_type': annotation_type, 'path_type': path_type,
              '_points': [_point(reader) for _ in range(count)],
              'origin': _point(reader), 'extrusion': _point(reader),
              'horizontal_direction': _point(reader),
              'leader_offset_block_ref': _point(reader)}
    result['endpoint_projection'] = _point(reader)
    if version < b'AC1015':
        result['dim_gap'] = reader.double()
    # R2010+ leaders whose annotation is an MTEXT (type 0) or absent (type 3)
    # no longer store the text box here.
    if version < b'AC1024' or annotation_type not in (0, 3):
        result['text_height'], result['text_width'] = reader.double(), reader.double()
    result['hookline_direction'] = reader.bits(1)
    result['has_arrowhead'] = bool(reader.bits(1))
    result['_unknown_short'], result['_unknown_bits'] = 0, (0, 0)
    if version < b'AC1015':
        # R13-R14 only: arrowhead type, DIMASZ, and a run of unknown flags.
        result['arrowhead_type'] = reader.short()
        result['arrow_size'] = reader.double()
        result['_legacy_unknown'] = (reader.bits(1), reader.bits(1), reader.short(),
                                     reader.short(), reader.bits(1), reader.bits(1))
    elif r18:
        remaining = getattr(reader, 'limit', len(reader.data) * 8) - reader.pos
        if remaining >= 2:
            result['_unknown_short'] = reader.short()
        remaining = getattr(reader, 'limit', len(reader.data) * 8) - reader.pos
        if remaining >= 2:
            result['_unknown_bits'] = (reader.bits(1), reader.bits(1))
    else:
        result['_unknown_short'] = reader.short()
        result['_unknown_bits'] = (reader.bits(1), reader.bits(1))
    return result


def decode_helix(reader, *, r2013_plus=False):
    result = _spline(reader, r18=r2013_plus)
    result['_helix'] = {
        'major_release_number': reader.long(),
        'maintenance_release_number': reader.long(),
        'axis_base_point': _point(reader),
        'start_point': _point(reader),
        'axis_vector': _point(reader),
        'radius': reader.double(), 'turns': reader.double(), 'turn_height': reader.double(),
        'handedness': reader.bits(1), 'constrain': reader.bits(8),
    }
    return result


def _mline(reader):
    scale, justification = reader.double(), reader.bits(8)
    start, extrusion = _point(reader), _point(reader)
    flags, element_count, count = reader.short(), reader.bits(8), reader.short()
    if count < 2 or not element_count or count > (len(reader.data) * 8 - reader.pos) // 18:
        raise DwgFormatError('invalid MLINE vertex or element count')

    def parameters():
        size = reader.short()
        if size < 0 or size > (len(reader.data) * 8 - reader.pos) // 2:
            raise DwgFormatError('invalid MLINE parameter count')
        return tuple(reader.double() for _ in range(size))

    vertices = []
    for _ in range(count):
        location, line, miter = _point(reader), _point(reader), _point(reader)
        elements = [(parameters(), parameters()) for _ in range(element_count)]
        vertices.append((location, line, miter, elements))
    if vertices[0][0] != start:
        raise DwgFormatError('MLINE start does not match its first vertex')
    return {'scale_factor': scale, 'justification': justification, 'extrusion': extrusion,
            'flags': flags, 'style_element_count': element_count, '_vertices': vertices}


def read_mline_style(reader, text, *, true_color=False, handle_linetypes=False):
    def color():
        index = reader.short()
        if not true_color:
            return index
        raw_color = reader.long() & 0xFFFFFFFF
        flags = reader.bits(8)
        if flags & 1:
            text()
        if flags & 2:
            text()
        return {0xC0: 256, 0xC1: 0, 0xC3: raw_color & 255}.get(raw_color >> 24)

    name, description = text(), text()
    dwg_flags = reader.short()
    flags = dwg_flags & 272
    for source, dest in ((1, 2), (2, 1), (32, 64), (64, 32), (512, 1024), (1024, 512)):
        if dwg_flags & source:
            flags |= dest
    fill, start, end = color(), math.degrees(reader.double()), math.degrees(reader.double())
    elements = [(reader.double(), color(), None if handle_linetypes else reader.short())
                for _ in range(reader.bits(8))]
    return {'name': name, 'description': description, 'flags': flags,
            'fill_color': fill, 'start_angle': start, 'end_angle': end, 'elements': elements}


def attach_mline_styles(entities, styles):
    for entity in entities:
        if entity['type'] == 'MLINE':
            attributes = entity['attributes']
            attributes['_style'] = styles.get(attributes.pop('mline_style_handle'))


def _region(reader, endbit):
    empty = bool(reader.bits(1))
    unknown = reader.bits(1)
    version = reader.short()
    if version != 1:
        return None

    sat_data = bytearray()
    if not empty:
        while True:
            size = reader.long()
            if size < 0 or size > (endbit - reader.pos) // 8:
                raise DwgFormatError('invalid REGION SAT block size')
            if not size:
                break
            for value in reader.raw(size):
                if 0x20 <= value <= 0x7e:
                    value = 0x9f - value
                if value == 9:
                    value = 0x20
                sat_data.append(value)

    wireframe = None
    if reader.bits(1):
        point = _point(reader) if reader.bits(1) else None
        isoline_count = reader.long()
        isolines_present = bool(reader.bits(1))

        def read_wire():
            wire = {'type': reader.bits(8), 'selection_marker': reader.long(),
                    'color': reader.short(), 'acis_index': reader.long()}
            point_count = reader.long()
            if point_count < 0 or point_count > (endbit - reader.pos) // 6:
                raise DwgFormatError('invalid REGION wire point count')
            wire['points'] = [_point(reader) for _ in range(point_count)]
            if reader.bits(1):
                wire['transform'] = {
                    'axes_translation': [_point(reader) for _ in range(4)],
                    'scale': reader.double(),
                    'flags': [reader.bits(1) for _ in range(3)]}
            return wire

        wire_count = reader.long()
        if wire_count < 0 or wire_count > (endbit - reader.pos) // 17:
            raise DwgFormatError('invalid REGION wire count')
        wires = [read_wire() for _ in range(wire_count)]
        silhouette_count = reader.long()
        if silhouette_count < 0 or silhouette_count > (endbit - reader.pos) // 23:
            raise DwgFormatError('invalid REGION silhouette count')
        silhouettes = []
        for _ in range(silhouette_count):
            silhouette = {'viewport_id': reader.long(), 'target': _point(reader),
                          'direction': _point(reader), 'up': _point(reader),
                          'perspective': bool(reader.bits(1))}
            count = reader.long()
            if count < 0 or count > (endbit - reader.pos) // 17:
                raise DwgFormatError('invalid REGION silhouette wire count')
            silhouette['wires'] = [read_wire() for _ in range(count)]
            silhouettes.append(silhouette)
        wireframe = {'point': point, 'isoline_count': isoline_count,
                     'isolines_present': isolines_present, 'wires': wires,
                     'silhouettes': silhouettes}

    acis_empty = bool(reader.bits(1))
    if not acis_empty:
        return None
    return {'acis_empty': empty, 'unknown': unknown, 'version': version,
            '_sat_data': sat_data.decode('latin1'), '_wireframe': wireframe}


def decode_image(reader, *, r2010_plus=False):
    """IMAGE payload (ODA specification 20.4.4x / LibreDWG dwg.spec).

    Handles (imagedef, imagedef reactor) follow in the entity handle stream.
    """
    result = {'class_version': reader.long(),
              'insert': _point(reader), 'u_pixel': _point(reader),
              'v_pixel': _point(reader),
              'image_size': (reader.rd(), reader.rd()),
              'flags': reader.short(),
              'clipping': reader.bits(1),
              'brightness': reader.bits(8),
              'contrast': reader.bits(8),
              'fade': reader.bits(8)}
    if r2010_plus:
        result['clip_mode'] = reader.bits(1)
    boundary_type = reader.short()
    if boundary_type == 1:
        count = 2
    else:
        count = reader.long()
    if count < 2 or count > 100000:
        raise DwgFormatError('invalid IMAGE clip boundary count')
    result['clipping_boundary_type'] = boundary_type
    result['_boundary'] = [(reader.rd(), reader.rd()) for _ in range(count)]
    return result


def _parse_image_def(reader, encoding):
    """IMAGEDEF payload in DWG field order (works for inline and stream text)."""
    class_version = reader.long()
    if not 0 <= class_version <= 10:
        raise DwgFormatError(f'invalid IMAGEDEF class version {class_version}')
    image_size = (reader.rd(), reader.rd())
    if not (0 < image_size[0] < 1e7 and 0 < image_size[1] < 1e7):
        raise DwgFormatError('invalid IMAGEDEF image size')
    if getattr(reader, 'string_reader', None) is None:
        size = reader.short()
        if size < 0 or size > 4096:
            raise DwgFormatError('invalid IMAGEDEF path length')
        raw = reader.raw(size)
        if encoding == 'utf-16le' and len(raw) % 2 == 0 and all(
                byte == 0 for byte in raw[1::2]):
            text = raw.decode('utf-16le', errors='replace')
        elif encoding == 'utf-16le':
            text = raw.decode('cp1252', errors='replace')
        else:
            text = raw.decode(encoding, errors='replace')
    else:
        text = reader.text(encoding)
    is_loaded = bool(reader.bits(1))
    resunits = reader.bits(8)
    pixel_size = (reader.rd(), reader.rd())
    if not (0 < pixel_size[0] < 1e4 and 0 < pixel_size[1] < 1e4):
        raise DwgFormatError('invalid IMAGEDEF pixel size')
    return {'class_version': class_version, 'image_size': image_size,
            'file_path': text.removesuffix('\x00'), 'is_loaded': is_loaded,
            'resunits': resunits, 'pixel_size': pixel_size}


def decode_image_def(reader, encoding):
    """IMAGEDEF object payload.

    R2004 files put a short object header before the payload and store the
    filename inline (not in the string stream), so this tries a direct parse
    first and then scans a small bit window for a valid payload.
    """
    from ._native_r18_objects import _ObjectReader
    data_end = getattr(reader, 'limit', len(reader.data) * 8)
    base = reader.pos
    try:
        reader.pos = base
        return _parse_image_def(reader, encoding)
    except (DwgFormatError, ValueError, IndexError, struct.error):
        pass
    reader.pos = base
    string_reader = getattr(reader, 'string_reader', None)
    for offset in range(1, 400):
        string_pos = string_reader.pos if string_reader is not None else None
        try:
            candidate = _ObjectReader(reader.data, base + offset, data_end,
                                      string_reader)
            result = _parse_image_def(candidate, encoding)
            reader.pos = candidate.pos
            return result
        except (DwgFormatError, ValueError, IndexError, struct.error):
            if string_pos is not None:
                string_reader.pos = string_pos
            continue
    raise DwgFormatError('IMAGEDEF payload not found')


def decode_mesh(reader):
    """SubDMesh payload (version 2), reversed from ODA DXF + DWG records.

    Fields: version BS, watertight B, subdivision vertex/vertex arrays (3BD),
    flat face list (count + indices per face, BL), edges (BL pairs), edge
    creases (BD) and two trailing bits.
    """
    version = reader.short()
    watertight = bool(reader.bits(1))
    num_subdiv = reader.long()
    if num_subdiv < 0 or num_subdiv > 1000000:
        raise DwgFormatError('invalid MESH subdivision vertex count')
    subdiv_vertices = [_point(reader) for _ in range(num_subdiv)]
    num_vertices = reader.long()
    if num_vertices < 0 or num_vertices > 1000000:
        raise DwgFormatError('invalid MESH vertex count')
    vertices = [_point(reader) for _ in range(num_vertices)]
    num_face_items = reader.long()
    if num_face_items < 0 or num_face_items > 4000000:
        raise DwgFormatError('invalid MESH face list size')
    faces = []
    face_list = [reader.long() for _ in range(num_face_items)]
    position = 0
    while position < len(face_list):
        size = face_list[position]
        position += 1
        if size < 3 or size > 16 or position + size > len(face_list):
            raise DwgFormatError('invalid MESH face index count')
        faces.append(face_list[position:position + size])
        position += size
    num_edges = reader.long()
    if num_edges < 0 or num_edges > 4000000:
        raise DwgFormatError('invalid MESH edge count')
    edges = [(reader.long(), reader.long()) for _ in range(num_edges)]
    num_creases = reader.long()
    if num_creases < 0 or num_creases > 4000000:
        raise DwgFormatError('invalid MESH crease count')
    creases = [reader.double() for _ in range(num_creases)]
    unknown_b1 = reader.bits(1)
    unknown_b2 = reader.bits(1)
    return {'version': version, 'watertight': watertight,
            '_subdiv_vertices': subdiv_vertices, '_vertices': vertices,
            '_faces': faces, '_edges': edges, '_creases': creases,
            '_mesh_tail_bits': (unknown_b1, unknown_b2)}


def _cmc_color(reader):
    """Read a CmColor (R2004+): BS index, BL RGB, RC flags, optional names."""
    index = reader.short()
    rgb = reader.long() & 0xFFFFFFFF
    flags = reader.bits(8)
    strings = getattr(reader, 'string_reader', None)
    for bit in (1, 2):
        if flags & bit:
            if strings is None:
                raise DwgFormatError('CMC color name requires the object string stream')
            strings.text('utf-16le')
    return index, rgb, flags


def _shape(reader):
    """SHAPE fields (ODA specification 20.4.37).

    The glyph itself lives in an external SHX shape file, which is not part of
    the DWG.  Callers consume the record but cannot render it without that file.
    """
    insert, scale = _point(reader), reader.double()
    rotation = math.degrees(reader.double())
    width = reader.double()
    oblique = math.degrees(reader.double())
    thickness = reader.double()
    number = reader.short()
    extrusion = _point(reader)
    return {'insert': insert, 'scale': scale, 'rotation': rotation,
            'width': width, 'oblique': oblique, 'thickness': thickness,
            'shape_number': number, 'extrusion': extrusion}


def _mtext(reader, *, split_string=False, r18=False, legacy=False, r2018=True, rect_height_present=True):
    insert, extrusion, text_direction = _point(reader), _point(reader), _point(reader)
    width = reader.double()
    rect_height = reader.double() if r18 and rect_height_present else None
    char_height = reader.double()
    attachment_point, flow_direction = reader.short(), reader.short()
    extents_height, extents_width = reader.double(), reader.double()
    result = {'insert': insert, 'extrusion': extrusion,
              'text_direction': text_direction, 'width': width,
              'char_height': char_height, 'attachment_point': attachment_point,
              'flow_direction': flow_direction,
              'rect_height': extents_height if rect_height is None else rect_height,
              'rect_width': width if r18 else extents_width}
    if split_string:
        result['_text_bytes'] = reader.text().encode('utf-8')
    else:
        length = reader.short()
        if length < 0:
            raise DwgFormatError('negative MTEXT byte length')
        result['_text_bytes'] = reader.raw(length)
    if not legacy:
        # R13/R14 have no line spacing; the field was introduced in R2000.
        result['line_spacing_style'] = reader.short()
        result['line_spacing_factor'] = reader.double()
        reader.bits(1)  # R2000 reserved/unknown bit, before the handle stream.
    if r18:
        background_flags = reader.long()
        if background_flags & 0x11:
            # ODA specification 20.4.46: scale factor, CmColor and
            # transparency follow; 0x10 (text frame) uses them since R2018.
            result['box_fill_scale'] = reader.double()
            index, rgb, _flags = _cmc_color(reader)
            result['bg_fill_color'] = index
            if (rgb >> 24) in (0xC2, 0xC3):
                result['bg_fill_true_color'] = rgb & 0xFFFFFF
            result['bg_fill_transparency'] = reader.long() & 0xFF
            result['bg_fill'] = background_flags & 0x13
        not_annotative = reader.bits(1) if r2018 else False
        if not_annotative:
            reader.short()  # version
            reader.bits(1)  # default flag
            reader.long()  # redundant attachment point
            for _ in range(10):
                reader.double()  # redundant axes, insertion, width and extents
            column_type = reader.short()
            if column_type:
                height_count = reader.long()
                reader.double()  # column width
                reader.double()  # column gutter
                auto_height = reader.bits(1)
                reader.bits(1)  # flow reversed
                if column_type == 2 and not auto_height:
                    for _ in range(height_count):
                        reader.double()
    return result


def _ellipse(reader):
    return {'center': _point(reader), 'major_axis': _point(reader),
            'extrusion': _point(reader), 'ratio': reader.double(),
            'start_param': reader.double(), 'end_param': reader.double()}


def _solid(reader, *, legacy=False):
    # R13/R14 store thickness as a plain BD and extrusion as 3BD; the BT/BE
    # bit-prefix forms were introduced in R2000.
    result = {'thickness': reader.double() if legacy else _thickness(reader)}
    elevation = reader.double()
    for index in range(4):
        result[f'vtx{index}'] = (reader.rd(), reader.rd(), elevation)
    result['extrusion'] = _point(reader) if legacy else _extrusion(reader)
    return result


def _insert(reader, *, r18=False, legacy=False):
    result = {'insert': _point(reader)}
    if legacy:
        # R13/R14 store the three scale factors unconditionally.
        scale = (reader.double(), reader.double(), reader.double())
    else:
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
    if r18 and result['_has_attribs']:
        result['_attribute_count'] = reader.long()
    return result


def decode_entity(type_code, reader, *, split_string=False, r18=False, legacy=False,
                  version=b'AC1015'):
    """Read supported entity data, leaving trailing handles untouched.

    ``legacy`` marks R13/R14 (AC1012/AC1014), whose common entity data and TEXT
    payload differ from R2000; other entity payloads keep the R2000 field order.
    Reserved keys: _points carries LWPOLYLINE x/y/start-width/end-width/bulge;
    _text_bytes preserves source text bytes; _has_attribs selects INSERT tails.
    TEXT/MTEXT STYLE and INSERT BLOCK_HEADER handles follow common entity handles.
    """
    if type_code == 1:
        return _text(reader, split_string=split_string, legacy=legacy)
    if type_code == 0x2c:
        return _mtext(reader, split_string=split_string, r18=r18, legacy=legacy)
    if type_code == 7:
        return _insert(reader, r18=r18, legacy=legacy)
    if type_code == 0x2d:
        return _leader(reader, r18=r18, version=version)
    if type_code in (0x28, 0x29):
        return {'start': _point(reader), 'unit_vector': _point(reader)}
    if type_code == 0x2f:
        return _mline(reader)
    if type_code in (0x1f, 0x20):
        return _solid(reader, legacy=legacy)
    if type_code == 0x4d:
        return _lwpolyline(reader, legacy=legacy)
    decoder = {0x23: _ellipse, 0x24: _spline}.get(type_code)
    return decoder(reader) if decoder else None
