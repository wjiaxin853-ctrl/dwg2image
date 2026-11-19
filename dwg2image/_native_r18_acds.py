"""Read small ACIS SAB records from the R18 AcDs data-storage section."""
import struct

from ._native_bits import DwgFormatError


_SEGMENT_MARKER = b'\xac\xd5'
_ACIS_SIGNATURES = (b'ASM BinaryFile', b'ACIS BinaryFile')


def read_acds_sab_records(data):
    """Return inline SAB blobs keyed by their AcDs object handles."""
    if len(data) < 128 or data[:4] != b'jard':
        return {}
    if struct.unpack_from('<H', data, 4)[0] != 128:
        return {}
    declared_size = struct.unpack_from('<I', data, 52)[0]
    if declared_size != len(data):
        raise DwgFormatError('AcDs file size does not match its section')

    records = {}
    pos = 0
    while True:
        pos = data.find(_SEGMENT_MARKER, pos)
        if pos < 0:
            break
        if pos + 48 <= len(data) and data[pos + 2:pos + 8] == b'_data_':
            segment_size = struct.unpack_from('<I', data, pos + 16)[0]
            segment_end = pos + segment_size
            if segment_size < 48 or segment_end > len(data):
                raise DwgFormatError('AcDs data segment exceeds its section')

            blob_start = pos + struct.unpack_from('<I', data, pos + 36)[0] * 16
            table_pos = pos + 48
            if blob_start < table_pos or blob_start > segment_end:
                raise DwgFormatError('invalid AcDs object-data alignment offset')

            entries = []
            while table_pos + 20 <= blob_start:
                column_size, _schema_revision, handle, blob_offset = struct.unpack_from(
                    '<IIQI', data, table_pos)
                if column_size != 20:
                    break
                entries.append((handle, blob_offset))
                table_pos += 20

            for handle, blob_offset in entries:
                blob_pos = blob_start + blob_offset
                if blob_pos + 4 > segment_end:
                    raise DwgFormatError('AcDs object-data record exceeds its segment')
                blob_size = struct.unpack_from('<I', data, blob_pos)[0]
                blob_end = blob_pos + 4 + blob_size
                if blob_end > segment_end:
                    raise DwgFormatError('AcDs SAB blob exceeds its segment')
                blob = data[blob_pos + 4:blob_end]
                if blob.startswith(_ACIS_SIGNATURES):
                    if handle in records:
                        raise DwgFormatError(f'duplicate AcDs SAB record for handle {handle:X}')
                    records[handle] = blob
        pos += 2

    return records
