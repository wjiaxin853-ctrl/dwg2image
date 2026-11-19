"""R2010+ BLOCK_HEADER data and owned-object vectors."""
from dataclasses import dataclass

from ._native_bits import DwgFormatError, resolve_handle


@dataclass
class R18Block:
    handle: int
    name: str
    base_point: tuple[float, float, float]
    xref_path: str
    description: str
    flag64: int
    xref_index_plus_one: int
    xref_dependent: int
    flags: tuple[int, ...]
    owned_handles: list[int]
    block_entity_handle: int
    endblk_handle: int
    layout_handle: int
    insert_handles: list[int]
    preview_size: int
    insert_units: int
    explodable: int
    block_scaling: int


def _ref(reader, owner):
    return resolve_handle(reader.handle(), owner)


def _read_block(record):
    reader = record.data_reader
    reactor_count = reader.long()
    if reactor_count < 0:
        raise DwgFormatError(f'negative reactor count in BLOCK_HEADER {record.handle:X}')
    xdictionary_missing = reader.bits(1)
    if record.r2013_plus:
        reader.bits(1)  # separate data-store flag
    name = reader.text()
    inline_text = record.version == b'AC1018'
    flag64 = reader.bits(1) if inline_text else 0
    xref_index = reader.short()
    xref_dependent = reader.bits(1) if inline_text else bool(xref_index & 256)
    flags = tuple(reader.bits(1) for _ in range(5))
    owned_count = 0 if any(flags[2:4]) else reader.long()
    if owned_count < 0:
        raise DwgFormatError(f'negative owned-object count in BLOCK_HEADER {record.handle:X}')
    base_point = tuple(reader.double() for _ in range(3))
    xref_path = reader.text()

    insert_count = 0
    while True:
        value = reader.bits(8)
        if value == 0:
            break
        insert_count += 1
    description = reader.text()
    preview_size = reader.long()
    if preview_size < 0:
        raise DwgFormatError(f'negative block preview size for handle {record.handle:X}')
    reader.skip(preview_size * 8)
    insert_units = reader.short() if not inline_text else 0
    explodable = reader.bits(1) if not inline_text else 1
    block_scaling = reader.bits(8) if not inline_text else 0
    if reader.pos != record.data_end:
        raise DwgFormatError(f'BLOCK_HEADER {record.handle:X}: data ends at '
                             f'{reader.pos}, expected {record.data_end}')
    if reader.string_reader is not None and reader.string_reader.pos != reader.string_reader.limit:
        raise DwgFormatError(f'BLOCK_HEADER {record.handle:X}: string stream ends at '
                             f'{reader.string_reader.pos}, expected '
                             f'{reader.string_reader.limit}')
    handles = record.handle_reader
    _ref(handles, record.handle)  # block control
    for _ in range(reactor_count):
        _ref(handles, record.handle)
    if not xdictionary_missing:
        _ref(handles, record.handle)
    _ref(handles, record.handle)  # null handle
    block_entity = _ref(handles, record.handle)
    owned = [_ref(handles, record.handle) for _ in range(owned_count)]
    endblk = _ref(handles, record.handle)
    inserts = [_ref(handles, record.handle) for _ in range(insert_count)]
    layout = _ref(handles, record.handle)
    if handles.limit - handles.pos > 7:
        raise DwgFormatError(f'BLOCK_HEADER {record.handle:X}: unparsed handle data')
    return R18Block(record.handle, name, base_point, xref_path, description,
                    flag64, xref_index, xref_dependent, flags, owned,
                    block_entity, endblk, layout, inserts, preview_size,
                    insert_units, explodable, block_scaling)


def read_r18_blocks(objects):
    """Parse block records and return their owned-object mapping by handle."""
    blocks = {}
    owner_by_handle = {}
    for record in objects.values():
        if record.kind != 0x31:
            continue
        block = _read_block(record)
        if not block.name:
            raise DwgFormatError(f'invalid or duplicate BLOCK_HEADER {block.handle:X}')
        blocks[block.handle] = block
        for handle in block.owned_handles:
            if handle in owner_by_handle:
                raise DwgFormatError(f'object {handle:X} has multiple block owners')
            owner_by_handle[handle] = block.handle
    if not blocks:
        raise DwgFormatError('R2010 DWG has no BLOCK_HEADER records')
    return blocks, owner_by_handle
