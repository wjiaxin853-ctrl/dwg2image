"""R2010+ common entity fields and their handle references."""
import math

from ._native_bits import DwgFormatError, resolve_handle
from ._native_r18_objects import _BoundedReader, _ObjectReader


def read_r18_common(record):
    """Read common entity data from an AC1027/AC1032 object record."""
    reader = record.data_reader
    graphic = reader.bits(1)
    graphic_data = None
    if graphic:
        size_bytes = reader.bits(3) if record.version >= b'AC1024' else 4
        size = int.from_bytes(reader.raw(size_bytes), 'little')
        graphic_data = reader.raw(size)

    mode = reader.bits(2)
    reactors = reader.long()
    if mode == 3 or reactors < 0:
        raise DwgFormatError(f'invalid R2010 entity mode or reactor count for {record.handle:X}')

    xdictionary_missing = reader.bits(1)
    has_ds_data = reader.bits(1) if record.r2013_plus else 0
    raw_color = reader.short() & 0xFFFF
    color_flags = raw_color & 0xFF00
    color_index = raw_color & 0x01FF
    true_color = (reader.long() & 0xFFFFFF
                  if color_flags & 0x8000 and not color_flags & 0x4000 else None)
    transparency = reader.long() if color_flags & 0x2000 else None
    color_name = reader.text() if color_flags & 0x4100 == 0x4100 else None
    color_book = reader.text() if color_flags & 0x4200 == 0x4200 else None

    ltscale = reader.double()
    linetype_flags = reader.bits(2)
    plotstyle_flags = reader.bits(2)
    material_flags = reader.bits(2) if record.version >= b'AC1021' else 0
    shadow_flags = reader.bits(8) if record.version >= b'AC1021' else 0
    visualstyle_flags = tuple(reader.bits(1) for _ in range(3)) if record.version >= b'AC1024' else ()
    invisible = reader.short()
    lineweight = reader.bits(8)
    return {
        'mode': mode,
        'reactors': reactors,
        'xdictionary_missing': bool(xdictionary_missing),
        'has_ds_data': bool(has_ds_data),
        'color': color_index,
        'color_flags': color_flags,
        'true_color': true_color,
        'transparency': transparency,
        'color_name': color_name,
        'color_book': color_book,
        'ltscale': ltscale,
        'linetype': linetype_flags,
        'plotstyle': plotstyle_flags,
        'material': material_flags,
        'shadow': shadow_flags,
        'visualstyles': visualstyle_flags,
        'invisible': invisible,
        'lineweight': lineweight,
        'graphic_present': bool(graphic),
        'graphic_data': graphic_data,
    }


def read_r18_common_handles(record, common, owner_from_block):
    """Read common handle refs, leaving entity-specific refs for the caller."""
    reader = record.handle_reader
    owner = resolve_handle(reader.handle(), record.handle) if common['mode'] == 0 else owner_from_block
    reactors = [resolve_handle(reader.handle(), record.handle)
                for _ in range(common['reactors'])]
    xdictionary = None
    if not common['xdictionary_missing']:
        xdictionary = resolve_handle(reader.handle(), record.handle)
    color_handle = None
    if common['color_flags'] & 0x4000:
        color_handle = resolve_handle(reader.handle(), record.handle)
    layer = resolve_handle(reader.handle(), record.handle)
    linetype = resolve_handle(reader.handle(), record.handle) if common['linetype'] == 3 else None
    material = resolve_handle(reader.handle(), record.handle) if common['material'] == 3 else None
    shadow = resolve_handle(reader.handle(), record.handle) if common['shadow'] == 3 else None
    plotstyle = resolve_handle(reader.handle(), record.handle) if common['plotstyle'] == 3 else None
    visualstyles = tuple(resolve_handle(reader.handle(), record.handle) if present else None
                         for present in common['visualstyles'])
    return {
        'owner': owner,
        'reactors': reactors,
        'xdictionary': xdictionary,
        'color': color_handle,
        'layer': layer,
        'linetype': linetype,
        'material': material,
        'shadow': shadow,
        'plotstyle': plotstyle,
        'visualstyles': visualstyles,
    }


def decode_wipeout(record, owner_from_block):
    """Decode the R2018 WIPEOUT payload and its adjacent common entity fields."""
    matches = []
    for start in range(record.data_start, record.data_end):
        reader = _BoundedReader(record.body, start, record.data_end)
        try:
            class_version = reader.long()
            if not 0 <= class_version <= 10:
                continue
            insert = tuple(reader.double() for _ in range(3))
            u_pixel = tuple(reader.double() for _ in range(3))
            v_pixel = tuple(reader.double() for _ in range(3))
            image_size = (reader.rd(), reader.rd())
            display_props = reader.short()
            clipping = reader.bits(1)
            brightness, contrast, fade = (reader.bits(8) for _ in range(3))
            clip_mode = reader.bits(1)
            boundary_type = reader.short()
            if boundary_type == 1:
                count = 2
            elif boundary_type == 2:
                count = reader.long()
            else:
                continue
            if count < (3 if boundary_type == 2 else 2):
                continue
            if count * 128 > reader.limit - reader.pos:
                continue
            boundary = [(reader.rd(), reader.rd()) for _ in range(count)]
            if reader.pos != record.data_end:
                continue
        except (DwgFormatError, OverflowError, ValueError):
            continue

        numbers = (*insert, *u_pixel, *v_pixel, *image_size,
                   *(value for point in boundary for value in point))
        if (not all(math.isfinite(value) for value in numbers)
                or image_size[0] <= 0 or image_size[1] <= 0
                or not any(u_pixel) or not any(v_pixel)
                or clipping not in (0, 1) or clip_mode not in (0, 1)
                or max(brightness, contrast, fade) > 100):
            continue
        matches.append((start, {
            'class_version': class_version, 'insert': insert,
            'u_pixel': u_pixel, 'v_pixel': v_pixel,
            'image_size': image_size, 'display_props': display_props,
            'clipping': clipping, 'brightness': brightness,
            'contrast': contrast, 'fade': fade, 'clip_mode': clip_mode,
            'clipping_boundary_type': boundary_type,
            '_boundary_points': boundary,
        }))

    if len(matches) != 1:
        raise DwgFormatError(
            f'WIPEOUT {record.handle:X}: expected one complete raster payload, '
            f'found {len(matches)}'
        )
    payload_start, attributes = matches[0]

    common_matches = []
    original_reader = record.data_reader
    try:
        for start in range(record.data_start, payload_start):
            reader = _ObjectReader(record.body, start, payload_start, None)
            record.data_reader = reader
            try:
                common = read_r18_common(record)
            except (DwgFormatError, OverflowError, ValueError):
                continue
            if (reader.pos == payload_start
                    and not common['color_flags'] & 0x4100 == 0x4100
                    and not common['color_flags'] & 0x4200 == 0x4200
                    and math.isfinite(common['ltscale'])
                    and common['ltscale'] > 0):
                original_handle_reader = record.handle_reader
                handles_reader = _BoundedReader(
                    record.body, original_handle_reader.pos,
                    original_handle_reader.limit)
                record.handle_reader = handles_reader
                try:
                    handles = read_r18_common_handles(
                        record, common, owner_from_block)
                    if handles['owner'] != owner_from_block:
                        continue
                    resolve_handle(handles_reader.handle(), record.handle)
                    resolve_handle(handles_reader.handle(), record.handle)
                    if handles_reader.limit - handles_reader.pos <= 7:
                        common_matches.append(common)
                except (DwgFormatError, OverflowError, ValueError):
                    pass
                finally:
                    record.handle_reader = original_handle_reader
    finally:
        record.data_reader = original_reader
    if len(common_matches) != 1:
        raise DwgFormatError(
            f'WIPEOUT {record.handle:X}: expected one adjacent common header, '
            f'found {len(common_matches)}'
        )
    record.data_reader.pos = record.data_end
    return common_matches[0], attributes
