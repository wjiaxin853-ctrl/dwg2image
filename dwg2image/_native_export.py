"""Project parsed AC1015 facts into ezdxf, refusing unsupported visible content."""
from pathlib import Path
import tempfile
import shutil
from collections import Counter

from .native import NativeDrawing, UnsupportedDwgError, read_dwg
from ._native_bits import DwgFormatError


_LINEWEIGHTS = (0, 5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50,
                53, 60, 70, 80, 90, 100, 106, 120, 140, 158, 200, 211)


def _lineweight(code):
    if 0 <= code < len(_LINEWEIGHTS):
        return _LINEWEIGHTS[code]
    # Legacy code 28 in the supplied AC1015 drawings is exported by ODA as BYLAYER.
    if code == 28:
        return -1
    if code in (29, 30, 31):
        return 28 - code
    raise DwgFormatError(f'invalid lineweight code {code}')


def _region_polygons(sat_data):
    from ezdxf.acis.entities import load

    if not sat_data:
        raise UnsupportedDwgError('REGION has no ACIS SAT data')
    bodies = load(sat_data.replace('\x7f', ' '))
    polygons = []
    for body in bodies:
        lump = body.lump
        while not lump.is_none:
            shell = lump.shell
            if shell.is_none:
                raise UnsupportedDwgError('REGION contains an empty ACIS shell')
            face = shell.face
            while not face.is_none:
                if face.surface.type != 'plane-surface':
                    raise UnsupportedDwgError('REGION contains a non-planar face')
                loops = face.loops()
                if len(loops) != 1:
                    raise UnsupportedDwgError('REGION face holes are not implemented')
                first = loops[0].coedge
                coedge, seen, points = first, set(), []
                while not coedge.is_none and id(coedge) not in seen:
                    seen.add(id(coedge))
                    edge = coedge.edge
                    if edge.is_none or edge.curve.type != 'straight-curve':
                        raise UnsupportedDwgError('REGION contains a non-linear edge')
                    vertex = edge.end_vertex if coedge.sense else edge.start_vertex
                    points.append(vertex.point.location)
                    coedge = coedge.next_coedge
                if coedge is not first or len(points) < 3:
                    raise UnsupportedDwgError('REGION face boundary is not a closed polygon')
                if not body.transform.is_none:
                    points = list(body.transform.matrix.transform_vertices(points))
                polygons.append(points)
                face = face.next_face
            lump = lump.next_lump
    if not polygons:
        raise UnsupportedDwgError('REGION has no planar polygon boundary')
    return polygons


def _solid_edges(sab_data):
    from ezdxf.acis.api import load, mesh_from_body

    if not sab_data:
        raise UnsupportedDwgError('3DSOLID has no ACIS SAB data')
    try:
        bodies = load(sab_data)
        edges = {}
        for body in bodies:
            for mesh in mesh_from_body(body):
                for face in mesh.faces:
                    if len(face) < 3 or any(index < 0 or index >= len(mesh.vertices)
                                            for index in face):
                        raise UnsupportedDwgError('3DSOLID has an invalid tessellated face')
                    for index, start in enumerate(face):
                        end = face[(index + 1) % len(face)]
                        key = tuple(sorted((start, end)))
                        edges.setdefault(key, (mesh.vertices[start], mesh.vertices[end]))
    except UnsupportedDwgError:
        raise
    except Exception as exc:
        raise UnsupportedDwgError(f'3DSOLID SAB tessellation failed: {exc}') from exc
    if not edges:
        raise UnsupportedDwgError('3DSOLID SAB produced no mesh edges')
    return tuple(edges.values())


def to_dxf_document(drawing: NativeDrawing):
    """Build a new DXF from supported modelspace and reachable block content."""
    import ezdxf

    if drawing.unsupported_modelspace:
        raise UnsupportedDwgError(f'unimplemented modelspace entities: {drawing.unsupported_modelspace}')
    document = ezdxf.new('R2018')
    document.units = 0  # Source INSUNITS has not been decoded; do not invent physical units.
    for linetype in drawing.linetypes.values():
        if linetype['complex'] or linetype['name'] in document.linetypes:
            continue
        document.linetypes.new(linetype['name'], dxfattribs={
            'description': linetype['description'],
            'pattern': [linetype['length'], *linetype['dashes']],
        })

    def linetype_name(handle):
        if handle not in drawing.linetypes:
            raise DwgFormatError(f'missing linetype {handle:X}')
        linetype = drawing.linetypes[handle]
        if linetype['complex']:
            raise UnsupportedDwgError(f'complex linetype: {linetype["name"]}')
        return linetype['name']

    for layer in drawing.layers.values():
        flags = layer['flags']
        attributes = dict(color=-abs(layer['color']) if flags & 2 else abs(layer['color']),
                          flags=(flags & 1) | ((flags & 4) >> 1) | ((flags & 8) >> 1),
                          plot=int(bool(flags & 16)), lineweight=_lineweight((flags >> 5) & 31))
        pattern = drawing.linetypes.get(layer['linetype_handle'])
        if pattern is None:
            raise DwgFormatError('missing layer linetype')
        if not pattern['complex']:
            attributes['linetype'] = pattern['name']
        name = layer['name']
        record = document.layers.get(name) if name in document.layers else document.layers.new(name)
        record.dxf.update(attributes)
    for style in drawing.styles.values():
        attributes = {key: value for key, value in style.items() if key != 'name'}
        name = style['name']
        record = document.styles.get(name) if name in document.styles else document.styles.new(name)
        record.dxf.update(attributes)

    owned = {}
    block_name_counts = Counter(block['name'] for block in drawing.blocks.values())
    output_block_names = {
        handle: (block['name'] if block_name_counts[block['name']] == 1
                 else f'{block["name"]}{handle:X}')
        for handle, block in drawing.blocks.items()
    }
    for entity in drawing.entities:
        if entity['mode'] == 0:
            owned.setdefault(entity['owner'], []).append(entity)
    built = set()
    active = set()
    emitted = {}
    hatch_boundaries = []
    leader_annotations = []

    def build_block(handle):
        if handle in active:
            raise UnsupportedDwgError('cyclic block reference')
        if handle in built:
            return
        if handle not in drawing.blocks:
            raise DwgFormatError(f'missing block {handle:X}')
        block = drawing.blocks[handle]
        if drawing.unsupported_blocks.get(handle):
            raise UnsupportedDwgError(f'unimplemented block entities: {drawing.unsupported_blocks[handle]}')
        active.add(handle)
        attributes = {'xref_path': block['xref_path']} if block.get('xref_path') else None
        layout = document.blocks.new(output_block_names[handle], base_point=block['base_point'],
                                     dxfattribs=attributes)
        for entity in owned.get(handle, []):
            emit(entity, layout)
        active.remove(handle)
        built.add(handle)

    def emit(entity, layout):
        attributes = dict(entity['attributes'])
        if entity['layer_handle'] not in drawing.layers:
            raise DwgFormatError(f'missing layer for entity {entity["handle"]}')
        layer = drawing.layers[entity['layer_handle']]
        linetype_name(layer['linetype_handle'])
        flag = entity['linetype_flag']
        pattern = ('BYLAYER', 'BYBLOCK', 'CONTINUOUS')[flag] if flag < 3 else linetype_name(entity['linetype_handle'])
        attributes.update(layer=layer['name'], linetype=pattern,
                          color=entity['color'], invisible=entity['invisible'],
                          ltscale=entity['ltscale'], lineweight=_lineweight(entity['lineweight']))
        if entity.get('true_color') is not None:
            attributes['true_color'] = entity['true_color']
        if entity.get('transparency') is not None:
            attributes['transparency'] = entity['transparency']
        kind = entity['type']
        if kind in ('TEXT', 'MTEXT'):
            style = attributes.pop('style_handle')
            if style not in drawing.styles:
                raise DwgFormatError(f'missing text style {style:X}')
            attributes['style'] = drawing.styles[style]['name']
        elif kind == 'INSERT':
            has_attributes = attributes.pop('has_attributes', False)
            insert_attributes = attributes.pop('_attribs', [])
            if has_attributes and not insert_attributes:
                raise UnsupportedDwgError('INSERT attribute records are missing')
            block_handle = attributes.pop('block_handle')
            build_block(block_handle)
            attributes['name'] = output_block_names[block_handle]
        elif kind == 'POLYLINE_2D':
            points = attributes.pop('_points')
            attributes.pop('first_vertex_handle', None)
            attributes.pop('last_vertex_handle', None)
            attributes['smooth_type'] = attributes.pop('curve_type')
            elevation = attributes.pop('elevation')
            attributes['elevation'] = (0.0, 0.0, elevation)
            target = layout.add_polyline2d(
                [point[:5] for point in points], format='xyseb',
                close=bool(attributes['flags'] & 1), dxfattribs=attributes)
            for vertex, source in zip(target.vertices, points):
                vertex.dxf.flags = source[5]
                if source[6]:
                    vertex.dxf.tangent_dir = source[6]
            emitted[entity['handle']] = target.dxf.handle
            return
        elif kind == 'POLYLINE_3D':
            points = attributes.pop('_points')
            target = layout.add_polyline3d(
                points, close=bool(attributes['flags'] & 1), dxfattribs=attributes)
        elif kind == 'SPLINE':
            scenario = attributes.pop('scenario')
            degree = attributes.pop('degree')
            if scenario == 2:
                fit_points = attributes.pop('_fit_points')
                for key in ('start_tangent', 'end_tangent'):
                    if not any(attributes[key]):
                        attributes.pop(key)
                target = layout.add_spline(fit_points, degree=degree, dxfattribs=attributes)
            else:
                control_points = attributes.pop('_control_points')
                weights = attributes.pop('_weights')
                knots = attributes.pop('knots')
                flags = (4 if attributes.pop('rational') else 0)
                flags |= 1 if attributes.pop('closed') else 0
                flags |= 2 if attributes.pop('periodic') else 0
                attributes['flags'] = flags
                attributes['knot_tolerance'] = attributes.pop('knot_tolerance')
                attributes['control_point_tolerance'] = attributes.pop('control_tolerance')
                if weights:
                    target = layout.add_rational_spline(
                        control_points, weights, degree=degree, knots=knots,
                        dxfattribs=attributes)
                else:
                    target = layout.add_open_spline(
                        control_points, degree=degree, knots=knots,
                        dxfattribs=attributes)
        elif kind.startswith('DIMENSION_'):
            block_handle = attributes.pop('geometry_block_handle')
            attributes.pop('dimstyle_handle')
            if block_handle not in drawing.blocks:
                raise DwgFormatError(f'missing dimension geometry block {block_handle:X}')
            build_block(block_handle)
            flags = attributes.pop('_flags1')
            base_type = {'DIMENSION_ORDINATE': 6, 'DIMENSION_LINEAR': 0,
                         'DIMENSION_ALIGNED': 1, 'DIMENSION_ANG2LN': 2,
                         'DIMENSION_DIAMETER': 3, 'DIMENSION_RADIUS': 4,
                         'DIMENSION_ANG3PT': 5}[kind]
            dimension = dict(geometry=output_block_names[block_handle],
                             dimstyle='Standard', dimtype=base_type | (32 if flags & 2 else 0)
                             | (0 if flags & 1 else 128),
                             defpoint=attributes['defpoint'],
                             text_midpoint=attributes['text_midpoint'],
                             extrusion=attributes['extrusion'],
                             actual_measurement=attributes['actual_measurement'],
                             attachment_point=attributes['attachment_point'],
                             line_spacing_style=attributes['line_spacing_style'],
                             line_spacing_factor=attributes['line_spacing_factor'],
                             horizontal_direction=attributes['horizontal_direction'],
                             text_rotation=attributes['text_rotation'])
            for source, target_name in (('defpoint2', 'defpoint2'),
                                        ('defpoint3', 'defpoint3'),
                                        ('defpoint4', 'defpoint4'),
                                        ('defpoint5', 'defpoint5'),
                                        ('ext_line_rotation', 'oblique_angle'),
                                        ('dim_rotation', 'angle')):
                if source in attributes:
                    dimension[target_name] = attributes[source]
            if attributes.get('text'):
                dimension['text'] = attributes['text']
            attributes = dimension
        if kind == 'LWPOLYLINE':
            points = attributes.pop('_points')
            target = layout.add_lwpolyline(points, format='xyseb',
                                  close=bool(attributes['flags'] & 1), dxfattribs=attributes)
        elif kind == 'MTEXT':
            text = attributes.pop('text')
            target = layout.add_mtext(text, dxfattribs=attributes)
        elif kind == 'ATTDEF':
            tag = attributes.pop('tag')
            prompt = attributes.pop('prompt')
            text = attributes.pop('text')
            insert = attributes.pop('insert')
            style = attributes.pop('style_handle')
            if style not in drawing.styles:
                raise DwgFormatError(f'missing text style {style:X}')
            attributes['style'] = drawing.styles[style]['name']
            attributes['prompt'] = prompt
            target = layout.add_attdef(tag, insert=insert, text=text,
                                       dxfattribs=attributes)
        elif kind == 'LEADER':
            annotation_handle = attributes.pop('annotation_handle')
            points = attributes.pop('_points')
            attributes.pop('dimstyle_handle')
            attributes.pop('endpoint_projection')
            attributes.pop('_unknown_vector')
            attributes.pop('_unknown_short')
            attributes.pop('_unknown_bits')
            attributes['normal_vector'] = attributes.pop('extrusion')
            target = layout.add_leader(points, dimstyle='Standard',
                                       dxfattribs=attributes)
            if annotation_handle:
                leader_annotations.append((target, annotation_handle))
        elif kind == 'WIPEOUT':
            boundary = attributes.pop('_boundary_points')
            attributes['flags'] = attributes.pop('display_props')
            target = layout.new_entity('WIPEOUT', dxfattribs=attributes)
            target.set_boundary_path(boundary)
        elif kind == 'REGION':
            polygons = _region_polygons(attributes.pop('_sat_data'))
            for key in ('acis_empty', 'unknown', 'version', '_wireframe'):
                attributes.pop(key)
            target = None
            for points in polygons:
                polyline = layout.add_polyline3d(points, close=True,
                                                 dxfattribs=attributes)
                if target is None:
                    target = polyline
        elif kind == '3DSOLID':
            sab_data = attributes.pop('_sab_data', None)
            for key in ('_sat_data', 'acis_empty', 'unknown', 'version', '_wireframe'):
                attributes.pop(key, None)
            edges = _solid_edges(sab_data)
            target = None
            for start, end in edges:
                line = layout.add_line(start, end, dxfattribs=attributes)
                if target is None:
                    target = line
        elif kind == 'HATCH':
            paths = attributes.pop('_paths')
            lines = attributes.pop('_pattern_lines')
            seeds = attributes.pop('_seeds')
            target = layout.new_entity('HATCH', dxfattribs=attributes)
            for path in paths:
                if 'vertices' in path:
                    boundary = target.paths.add_polyline_path(path['vertices'],
                        is_closed=path['closed'], flags=path['flags'])
                else:
                    boundary = target.paths.add_edge_path(flags=path['flags'])
                    for source in path['edges']:
                        edge = dict(source)
                        edge_kind = edge.pop('type')
                        if edge_kind == 'line':
                            boundary.add_line(edge['start'], edge['end'])
                        elif edge_kind == 'arc':
                            boundary.add_arc(edge['center'], edge['radius'],
                                             edge['start_angle'], edge['end_angle'],
                                             edge['ccw'])
                        elif edge_kind == 'ellipse':
                            boundary.add_ellipse(edge['center'], edge['major_axis'],
                                                 edge['ratio'], edge['start_angle'],
                                                 edge['end_angle'], edge['ccw'])
                        elif edge_kind == 'spline':
                            boundary.add_spline(
                                control_points=edge['control_points'],
                                knot_values=edge['knot_values'],
                                weights=edge['weights'] or None,
                                degree=edge['degree'],
                                periodic=int(edge['periodic']))
                        else:
                            raise UnsupportedDwgError(f'HATCH {edge_kind} edges are not yet verified for export')
                hatch_boundaries.append((boundary, path['source_handles']))
            if not attributes['solid_fill']:
                target.set_pattern_definition(lines)
            if seeds:
                target.set_seed_points(seeds)
        elif kind in ('POLYLINE_3D', 'SPLINE'):
            pass
        else:
            target = layout.new_entity('DIMENSION' if kind.startswith('DIMENSION_') else kind,
                                       dxfattribs=attributes)
        if kind == 'INSERT':
            for source in insert_attributes:
                attribute = dict(source)
                tag = attribute.pop('tag')
                text = attribute.pop('text')
                insert = attribute.pop('insert')
                attribute.pop('field_length')
                style = attribute.pop('style_handle')
                if style not in drawing.styles:
                    raise DwgFormatError(f'missing text style {style:X}')
                attribute['style'] = drawing.styles[style]['name']
                target.add_attrib(tag, text, insert=insert, dxfattribs=attribute)
        emitted[entity['handle']] = target.dxf.handle

    for entity in drawing.modelspace():
        emit(entity, document.modelspace())
    for leader, annotation_handle in leader_annotations:
        annotation = emitted.get(f'{annotation_handle:X}')
        if annotation is None:
            raise UnsupportedDwgError(
                f'LEADER annotation {annotation_handle:X} is not exported'
            )
        leader.dxf.annotation_handle = annotation
    for boundary, handles in hatch_boundaries:
        if any(handle not in emitted for handle in handles):
            raise UnsupportedDwgError('HATCH references an unexported boundary entity')
        boundary.source_boundary_objects = [emitted[handle] for handle in handles]
    return document


def native_to_dxf(source: str | Path, destination: str | Path) -> Path:
    """Write an independently decoded DXF, refusing unsupported content."""
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    document = to_dxf_document(read_dwg(source))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='dwg2image-native-') as directory:
        staged = Path(directory) / 'drawing.dxf'
        document.saveas(staged)
        with destination.open('xb') as output, staged.open('rb') as converted:
            shutil.copyfileobj(converted, output)
    return destination
