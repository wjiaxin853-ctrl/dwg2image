"""R2018 layer, text-style, and linetype records."""
from ._native_bits import DwgFormatError, resolve_handle


def _object_prefix(record):
    reader = record.data_reader
    reactors = reader.long()
    if reactors < 0:
        raise DwgFormatError(f'negative reactor count in table record {record.handle:X}')
    xdictionary_missing = bool(reader.bits(1))
    has_ds_data = bool(reader.bits(1))
    return reader, reactors, xdictionary_missing, has_ds_data


def _common_table(record, reader):
    name = reader.text()
    xref_resolved = reader.short()
    return name, xref_resolved


def _handles(record, reactors, xdictionary_missing, extra):
    reader = record.handle_reader
    owner = resolve_handle(reader.handle(), record.handle)
    for _ in range(reactors):
        resolve_handle(reader.handle(), record.handle)
    if not xdictionary_missing:
        resolve_handle(reader.handle(), record.handle)
    xref = resolve_handle(reader.handle(), record.handle)
    values = [resolve_handle(reader.handle(), record.handle) for _ in range(extra)]
    if reader.limit - reader.pos > 7:
        raise DwgFormatError(f'table {record.handle:X}: unparsed handle data')
    return owner, xref, values


def _read_layer(record):
    reader, reactors, xdictionary_missing, has_ds_data = _object_prefix(record)
    name, xref_resolved = _common_table(record, reader)
    flags = reader.short()
    color_index = reader.short()
    raw_color = reader.long() & 0xFFFFFFFF
    color_method, color_rgb = raw_color >> 24, raw_color & 0xFFFFFF
    color_flags = reader.bits(8)
    color_name = reader.text() if color_flags & 1 else None
    color_book = reader.text() if color_flags & 2 else None
    if reader.pos != record.data_end:
        raise DwgFormatError(f'LAYER {record.handle:X}: data ends at {reader.pos}, expected {record.data_end}')
    if reader.string_reader and reader.string_reader.pos != reader.string_reader.limit:
        raise DwgFormatError(f'LAYER {record.handle:X}: string stream is not fully consumed')
    _, _, refs = _handles(record, reactors, xdictionary_missing, 4)
    plotstyle, material, linetype, visualstyle = refs
    if color_method == 0xC3:
        color_index = color_rgb & 0xFF
    if color_index == 0:
        color_index = 7
    return {
        'name': name, 'flags': flags, 'color': color_index,
        'off': bool(flags & 2), 'xref_resolved': xref_resolved,
        'has_ds_data': has_ds_data, 'color_method': color_method,
        'color_rgb': color_rgb, 'color_name': color_name,
        'color_book': color_book, 'plotstyle_handle': plotstyle,
        'material_handle': material, 'linetype_handle': linetype,
        'visualstyle_handle': visualstyle,
    }


def _read_style(record):
    reader, reactors, xdictionary_missing, has_ds_data = _object_prefix(record)
    name, xref_resolved = _common_table(record, reader)
    shape, vertical = reader.bits(1), reader.bits(1)
    height, width, oblique = reader.double(), reader.double(), reader.double()
    generation, last_height = reader.bits(8), reader.double()
    font, bigfont = reader.text(), reader.text()
    if reader.pos != record.data_end:
        raise DwgFormatError(f'STYLE {record.handle:X}: data ends at {reader.pos}, expected {record.data_end}')
    if reader.string_reader and reader.string_reader.pos != reader.string_reader.limit:
        raise DwgFormatError(f'STYLE {record.handle:X}: string stream is not fully consumed')
    _handles(record, reactors, xdictionary_missing, 0)
    return {
        'name': name, 'flags': shape | (vertical << 2),
        'height': height, 'width': width, 'oblique': oblique,
        'generation_flags': generation, 'last_height': last_height,
        'font': font, 'bigfont': bigfont,
    }


def _read_linetype(record):
    reader, reactors, xdictionary_missing, has_ds_data = _object_prefix(record)
    name, xref_resolved = _common_table(record, reader)
    description = reader.text()
    pattern_length = reader.double()
    alignment, count = reader.bits(8), reader.bits(8)
    if count < 0 or count > (record.data_end - reader.pos) // 2:
        raise DwgFormatError(f'LTYPE {record.handle:X}: invalid dash count')
    dashes, shape_flags = [], []
    complex_pattern, dot_shapes = False, True
    for _ in range(count):
        length = reader.double()
        shape_code = reader.short()
        x, y = reader.rd(), reader.rd()
        scale, rotation = reader.double(), reader.double()
        flags = reader.short()
        shape_flags.append(flags)
        complex_pattern |= bool(flags & ~1)
        dot_shapes &= (flags == 4 and shape_code == 0 and x == 0 and y == 0
                       and scale == 1 and rotation == 0)
        dashes.append(length)
    if any(flags & 2 for flags in shape_flags):
        reader.skip(512 * 8)
    if reader.pos != record.data_end:
        raise DwgFormatError(f'LTYPE {record.handle:X}: data ends at {reader.pos}, expected {record.data_end}')
    if reader.string_reader and reader.string_reader.pos != reader.string_reader.limit:
        raise DwgFormatError(f'LTYPE {record.handle:X}: string stream is not fully consumed')
    _, xref, shape_refs = _handles(record, reactors, xdictionary_missing, count)
    return {
        'name': name, 'description': description, 'length': pattern_length,
        'dashes': dashes, 'complex': complex_pattern and not dot_shapes,
        'dot_shapes': complex_pattern and dot_shapes,
        'alignment': alignment, 'shape_handles': shape_refs,
        'xref_resolved': xref_resolved, 'xref_handle': xref,
        'has_ds_data': has_ds_data,
    }


def read_r18_tables(objects):
    layers, styles, linetypes = {}, {}, {}
    for record in objects.values():
        if record.kind == 51:
            layers[record.handle] = _read_layer(record)
        elif record.kind == 53:
            styles[record.handle] = _read_style(record)
        elif record.kind == 57:
            linetypes[record.handle] = _read_linetype(record)
    return layers, styles, linetypes
