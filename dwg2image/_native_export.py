"""Project parsed AC1015 facts into ezdxf, refusing unsupported visible content."""
from pathlib import Path
import tempfile
import shutil

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
    for entity in drawing.entities:
        if entity['mode'] == 0:
            owned.setdefault(entity['owner'], []).append(entity)
    built = set()
    active = set()

    def build_block(handle):
        if handle in active:
            raise UnsupportedDwgError('cyclic block reference')
        if handle in built:
            return
        if handle not in drawing.blocks:
            raise DwgFormatError(f'missing block {handle:X}')
        block = drawing.blocks[handle]
        if block['external']:
            raise UnsupportedDwgError(f'external block reference: {block["name"]}')
        if drawing.unsupported_blocks.get(handle):
            raise UnsupportedDwgError(f'unimplemented block entities: {drawing.unsupported_blocks[handle]}')
        active.add(handle)
        layout = document.blocks.new(block['name'], base_point=block['base_point'])
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
        kind = entity['type']
        if kind == 'TEXT':
            style = attributes.pop('style_handle')
            if style not in drawing.styles:
                raise DwgFormatError(f'missing text style {style:X}')
            attributes['style'] = drawing.styles[style]['name']
        elif kind == 'INSERT':
            if attributes.pop('has_attributes', False):
                raise UnsupportedDwgError('INSERT attributes are not implemented')
            block_handle = attributes.pop('block_handle')
            build_block(block_handle)
            attributes['name'] = drawing.blocks[block_handle]['name']
        if kind == 'LWPOLYLINE':
            points = attributes.pop('_points')
            layout.add_lwpolyline(points, format='xyseb',
                                  close=bool(attributes['flags'] & 1), dxfattribs=attributes)
        else:
            layout.new_entity(kind, dxfattribs=attributes)

    for entity in drawing.modelspace():
        emit(entity, document.modelspace())
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
