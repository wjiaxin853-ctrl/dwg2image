"""AC1015 entity payload regressions independent of ODA runtime."""
import struct
import unittest

from dwg2image._native_bits import BitReader
from dwg2image._native_entities import decode_entity


def packed(bits):
    return int(bits.ljust((len(bits) + 7) // 8 * 8, '0'), 2).to_bytes(
        (len(bits) + 7) // 8, 'big')


def raw_bits(data):
    return ''.join(f'{byte:08b}' for byte in data)


class EntityPayloadTests(unittest.TestCase):
    def test_text_omitted_fields_and_raw_source_bytes(self):
        # All DataFlags set: default alignment, angles, generation and width.
        bits = '11111111' + raw_bits(struct.pack('<dd', 10, 20))
        bits += '11'  # Default extrusion and zero thickness.
        bits += raw_bits(struct.pack('<d', 2))
        bits += '01' + '00000010' + raw_bits(b'A\0')
        reader = BitReader(packed(bits))
        data = decode_entity(1, reader)
        self.assertEqual(reader.pos, len(bits))
        self.assertEqual(data['_text_bytes'], b'A\0')
        self.assertEqual(data['insert'], (10, 20, 0))
        self.assertEqual(data['align_point'], (10, 20, 0))
        self.assertEqual(data['width'], 1)
        self.assertEqual(data['height'], 2)
        self.assertEqual(data['rotation'], 0)

    def test_unbounded_polyline_count_rejected_before_allocation(self):
        # BS flag 0; BL full-width count far larger than the remaining stream.
        bits = '10' + '00' + raw_bits(struct.pack('<i', 2**30))
        with self.assertRaisesRegex(ValueError, 'available data'):
            decode_entity(0x4d, BitReader(packed(bits)))

    def test_negative_polyline_count_rejected(self):
        bits = '10' + '00' + raw_bits(struct.pack('<i', -1))
        with self.assertRaisesRegex(ValueError, 'array lengths'):
            decode_entity(0x4d, BitReader(packed(bits)))

    def test_unsupported_type_does_not_consume_stream(self):
        reader = BitReader(b'\xff')
        self.assertIsNone(decode_entity(0xffff, reader))
        self.assertEqual(reader.pos, 0)
