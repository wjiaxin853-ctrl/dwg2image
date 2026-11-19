"""R2018 DWG object reader for the independently implemented backend."""
from collections import Counter
from pathlib import Path

from ._native_bits import DwgFormatError, resolve_handle
from ._native_r18_blocks import read_r18_blocks
from ._native_r18_entities import (
    decode_wipeout, read_r18_common, read_r18_common_handles,
)
from ._native_r18_acds import read_acds_sab_records
from ._native_r18_objects import read_r18_objects
from ._native_r18_tables import read_r18_tables
from ._native_r2004 import read_r18_sections


_ENTITY_NAMES = {
    1: 'TEXT', 2: 'ATTRIB', 3: 'ATTDEF', 7: 'INSERT',
    10: 'VERTEX_2D', 11: 'VERTEX_3D', 15: 'POLYLINE_2D', 16: 'POLYLINE_3D',
    17: 'ARC', 18: 'CIRCLE', 19: 'LINE', 20: 'DIMENSION_ORDINATE',
    21: 'DIMENSION_LINEAR', 22: 'DIMENSION_ALIGNED', 23: 'DIMENSION_ANG3PT',
    24: 'DIMENSION_ANG2LN', 25: 'DIMENSION_RADIUS', 26: 'DIMENSION_DIAMETER',
    27: 'POINT', 28: '3DFACE', 29: 'POLYLINE_PFACE', 30: 'POLYLINE_MESH',
    31: 'SOLID', 32: 'TRACE', 34: 'VIEWPORT', 35: 'ELLIPSE', 36: 'SPLINE',
    37: 'REGION', 38: '3DSOLID', 44: 'MTEXT', 45: 'LEADER',
    47: 'MLINE', 77: 'LWPOLYLINE', 78: 'HATCH', 0x4B03: 'WIPEOUT',
}
_ENTITY_KINDS = set(range(1, 48)) - {42}
_ENTITY_KINDS.update((77, 78, 0x1F2, 0x4B03))
_DIMENSION_KINDS = {20, 21, 22, 23, 24, 25, 26}


def _decode_body(record):
    kind, reader = record.kind, record.data_reader
    from ._native_dimension import decode_dimension
    from ._native_entities import (
        _region, decode_attribute, decode_entity, decode_vertex2d,
        decode_vertex3d, _polyline2d, _polyline3d,
    )
    from ._native_hatch import decode_hatch
    from .native import _geometry

    if kind == 78:
        return decode_hatch(reader, r18=True)
    if kind in (2, 3):
        return decode_attribute(kind, reader, 'utf-8', split_string=True, r18=True)
    if kind in (20, 21, 22, 23, 24, 25, 26):
        return decode_dimension(kind, reader, split_string=True, r18=True)
    if kind in (15, 16):
        return _polyline2d(reader, r18=True) if kind == 15 else _polyline3d(reader, r18=True)
    if kind == 10:
        return decode_vertex2d(reader, r18=True)
    if kind == 11:
        return decode_vertex3d(reader)
    if kind in (37, 38):
        return _region(reader, record.data_end)
    if kind == 36:
        from ._native_entities import _spline
        return _spline(reader, r18=True)
    if kind in (17, 18, 19, 27):
        return _geometry(kind, reader)
    return decode_entity(kind, reader, split_string=True, r18=True)


def _read_type_handles(record, common, attributes, name):
    reader = record.handle_reader
    if name in ('TEXT', 'ATTRIB', 'ATTDEF', 'MTEXT'):
        attributes['style_handle'] = resolve_handle(reader.handle(), record.handle)
    elif name == 'INSERT':
        attributes['block_handle'] = resolve_handle(reader.handle(), record.handle)
        if attributes.pop('_has_attribs'):
            count = attributes.pop('_attribute_count')
            attributes['has_attributes'] = True
            for _ in range(count):
                resolve_handle(reader.handle(), record.handle)
            resolve_handle(reader.handle(), record.handle)  # SEQEND
    elif name.startswith('DIMENSION_'):
        attributes['dimstyle_handle'] = resolve_handle(reader.handle(), record.handle)
        attributes['geometry_block_handle'] = resolve_handle(reader.handle(), record.handle)
    elif name == 'LEADER':
        attributes['annotation_handle'] = resolve_handle(reader.handle(), record.handle)
        attributes['dimstyle_handle'] = resolve_handle(reader.handle(), record.handle)
    elif name == 'HATCH':
        for path, count in zip(attributes['_paths'], attributes.pop('_boundary_handle_counts')):
            path['source_handles'] = []
            for _ in range(count):
                handle = resolve_handle(reader.handle(), record.handle)
                if handle:
                    path['source_handles'].append(f'{handle:X}')
        attributes.pop('_gradient', None)
    elif name == 'WIPEOUT':
        attributes['image_def_handle'] = resolve_handle(reader.handle(), record.handle)
        attributes['image_def_reactor_handle'] = resolve_handle(reader.handle(), record.handle)
        remaining = reader.limit - reader.pos
        if remaining > 7:
            raise DwgFormatError(f'WIPEOUT {record.handle:X}: unparsed handle data')
    elif name in ('POLYLINE_2D', 'POLYLINE_3D'):
        count = attributes.pop('owned_count', 0)
        attributes['_vertex_handles'] = [
            resolve_handle(reader.handle(), record.handle) for _ in range(count)
        ]
        resolve_handle(reader.handle(), record.handle)  # SEQEND


def _finish_text(attributes):
    if '_text_bytes' in attributes:
        attributes['text'] = attributes.pop('_text_bytes').removesuffix(b'\x00').decode('utf-8')


def read_r18_dwg(source: str | Path):
    """Read AC1032 records without invoking ODA or another converter."""
    from .native import NativeDrawing, UnsupportedDwgError

    source = Path(source)
    data = source.read_bytes()
    sections = read_r18_sections(data)
    acds = next((section['data'] for section in sections.values()
                 if section['name'] == 'AcDb:AcDsPrototype_1b'), b'')
    sab_records = read_acds_sab_records(acds)
    _, objects = read_r18_objects(data, sections)
    r18_blocks, owner_by_handle = read_r18_blocks(objects)
    layers, styles, linetypes = read_r18_tables(objects)
    blocks = {
        handle: {
            'name': block.name, 'base_point': block.base_point,
            'external': bool(block.xref_path),
            'xref_path': block.xref_path,
        }
        for handle, block in r18_blocks.items()
    }

    entities = []
    vertices_by_handle = {}
    attributes_by_owner = {}
    unsupported = Counter()
    unsupported_blocks = {}

    for record in objects.values():
        kind = record.kind
        if kind in (4, 5, 6, 49, 51, 53, 57):
            continue
        if kind not in _ENTITY_KINDS and record.handle not in owner_by_handle:
            continue
        if kind not in _ENTITY_KINDS:
            owner = owner_by_handle[record.handle]
            name = _ENTITY_NAMES.get(kind, f'TYPE_{kind:X}')
            unsupported_blocks.setdefault(owner, Counter())[name] += 1
            continue

        if kind == 0x4B03:
            common, attributes = decode_wipeout(
                record, owner_by_handle.get(record.handle))
        else:
            common = read_r18_common(record)
        handles = read_r18_common_handles(record, common, owner_by_handle.get(record.handle))
        name = _ENTITY_NAMES.get(kind, f'TYPE_{kind:X}')
        if kind not in _ENTITY_KINDS:
            if common['mode'] == 2:
                unsupported[name] += 1
            elif handles['owner'] is not None:
                unsupported_blocks.setdefault(handles['owner'], Counter())[name] += 1
            continue

        if kind != 0x4B03:
            try:
                attributes = _decode_body(record)
            except (DwgFormatError, ValueError) as exc:
                if kind == 38 and record.handle in sab_records:
                    # The linked AcDs SAB is authoritative when the inline solid
                    # payload uses an unknown ACIS version.
                    record.data_reader.pos = record.data_end
                    attributes = {'_sab_data': sab_records[record.handle]}
                else:
                    raise UnsupportedDwgError(
                        f'R18 {name} {record.handle:X} payload is not decoded: {exc}'
                    ) from exc
        if kind == 38 and record.handle in sab_records:
            attributes = attributes or {}
            attributes['_sab_data'] = sab_records[record.handle]
            if record.data_reader.pos != record.data_end:
                # The linked SAB supplies the solid geometry; skip the remaining
                # version-specific inline ACIS and wireframe payload.
                record.data_reader.pos = record.data_end
        if attributes is None:
            if common['mode'] == 2:
                unsupported[name] += 1
            elif handles['owner'] is not None:
                unsupported_blocks.setdefault(handles['owner'], Counter())[name] += 1
            continue
        if record.data_reader.pos != record.data_end:
            raise DwgFormatError(
                f'{name} {record.handle:X}: data ends at {record.data_reader.pos}, '
                f'expected {record.data_end}'
            )
        string_reader = record.data_reader.string_reader
        if string_reader and string_reader.pos != string_reader.limit:
            raise DwgFormatError(
                f'{name} {record.handle:X}: string stream ends at '
                f'{string_reader.pos}, expected {string_reader.limit}'
            )

        _read_type_handles(record, common, attributes, name)
        _finish_text(attributes)
        if name == 'ATTRIB':
            owner = handles['owner']
            if owner is None:
                raise DwgFormatError(f'ATTRIB {record.handle:X}: missing INSERT owner')
            attributes_by_owner.setdefault(owner, []).append(attributes)
            continue
        if name in ('VERTEX_2D', 'VERTEX_3D'):
            if handles['owner'] is not None:
                attributes.update(handle=record.handle, owner=handles['owner'], type=kind)
                vertices_by_handle[record.handle] = attributes
            continue

        entities.append({
            'type': name, 'handle': f'{record.handle:X}', 'owner': handles['owner'],
            'layer_handle': handles['layer'], 'linetype_handle': handles['linetype'],
            'linetype_flag': common['linetype'], 'mode': common['mode'],
            'color': common['color'], 'true_color': common['true_color'],
            'transparency': common['transparency'], 'invisible': common['invisible'],
            'ltscale': common['ltscale'], 'lineweight': common['lineweight'],
            'attributes': attributes,
        })

    inserts = {int(entity['handle'], 16): entity for entity in entities if entity['type'] == 'INSERT'}
    for owner, attribs in attributes_by_owner.items():
        if owner not in inserts or not inserts[owner]['attributes'].get('has_attributes'):
            raise DwgFormatError(f'ATTRIB owner {owner:X} is not an attributed INSERT')
        inserts[owner]['attributes']['_attribs'] = attribs

    polylines = {int(entity['handle'], 16): entity for entity in entities
                 if entity['type'] in ('POLYLINE_2D', 'POLYLINE_3D')}
    for handle, entity in polylines.items():
        attributes = entity['attributes']
        expected_handles = attributes.pop('_vertex_handles')
        vertex_type = 10 if entity['type'] == 'POLYLINE_2D' else 11
        vertices = [vertices_by_handle[value] for value in expected_handles
                    if value in vertices_by_handle
                    and vertices_by_handle[value]['type'] == vertex_type]
        if len(vertices) != len(expected_handles) or any(vertex['owner'] != handle for vertex in vertices):
            raise DwgFormatError(f'polyline {handle:X}: owned vertex handles do not match owner records')
        if entity['type'] == 'POLYLINE_2D':
            start_width = attributes['default_start_width']
            end_width = attributes['default_end_width']
            attributes['_points'] = [
                (vertex['location'][0], vertex['location'][1],
                 vertex['start_width'] or start_width, vertex['end_width'] or end_width,
                 vertex['bulge'], vertex['flags'], vertex['tangent_dir'])
                for vertex in vertices
            ]
        else:
            attributes['_points'] = [vertex['location'] for vertex in vertices]

    return NativeDrawing(
        entities, layers, dict(unsupported), len(objects), styles, linetypes, blocks,
        {owner: dict(types) for owner, types in unsupported_blocks.items()},
    )
