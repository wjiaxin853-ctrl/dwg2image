"""Independent decoder regressions; real drawings are opt-in local fixtures."""
from collections import Counter
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from dwg2image import DwgFormatError, UnsupportedDwgError, dwg_to_dxf, dwg_to_png, read_dwg
from dwg2image._native_bits import BitReader, crc16, modular, resolve_handle
from dwg2image.native import _object_map


class NativeBoundaryTests(unittest.TestCase):
    def test_bit_codes_and_unaligned_reads(self):
        # Published BS example: 257, 0, 256, 15, 0.
        stream = '0000000001000000011011010000111110'
        stream += '0' * ((-len(stream)) % 8)
        reader = BitReader(int(stream, 2).to_bytes(len(stream) // 8, 'big'))
        self.assertEqual([reader.short() for _ in range(5)], [257, 0, 256, 15, 0])
        with self.assertRaises(DwgFormatError):
            reader.raw(100)
        with self.assertRaises(DwgFormatError):
            BitReader(b'\xc0').double()

    def test_modular_signed_and_unsigned_are_distinct(self):
        self.assertEqual(modular(bytes.fromhex('854b'), 0, 2, signed=True), (-1413, 2))
        self.assertEqual(modular(bytes.fromhex('854b'), 0, 2), (9605, 2))
        with self.assertRaises(DwgFormatError):
            modular(b'\x80', 0, 1)

    def test_default_double_patch_order(self):
        # Code 10: first two bytes patch indices 4/5, then four patch 0..3.
        payload = b'\x11\x22\x33\x44\x55\x66'
        bits = '10' + ''.join(f'{byte:08b}' for byte in payload)
        bits += '0' * ((-len(bits)) % 8)
        reader = BitReader(int(bits, 2).to_bytes(len(bits) // 8, 'big'))
        default = struct.unpack('<d', bytes.fromhex('000000000000f03f'))[0]
        result = struct.pack('<d', reader.dd(default))
        self.assertEqual(result, bytes.fromhex('334455661122f03f'))

    def test_handle_relative_codes(self):
        self.assertEqual(resolve_handle((6, 0), 100), 101)
        self.assertEqual(resolve_handle((12, 7), 100), 93)
        with self.assertRaises(DwgFormatError):
            BitReader(b'\x09').handle()

    def test_object_map_crc_truncation_and_terminator(self):
        # One page, handle +1 and address +8, followed by an empty end page.
        page = bytes.fromhex('00040108')
        ending = bytes.fromhex('0002')
        data = page + crc16(page).to_bytes(2, 'big') + ending + crc16(ending).to_bytes(2, 'big')
        self.assertEqual(list(_object_map(data, (0, len(data)))), [(1, 8)])
        corrupt = bytearray(data)
        corrupt[2] ^= 1
        with self.assertRaisesRegex(DwgFormatError, 'CRC'):
            list(_object_map(corrupt, (0, len(corrupt))))
        with self.assertRaises(DwgFormatError):
            list(_object_map(data[:-1], (0, len(data) - 1)))

    def test_native_rejects_other_versions_without_external_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'unsupported.dwg'
            source.write_bytes(b'AC1032' + bytes(64))
            with patch('subprocess.run', side_effect=AssertionError('external execution')):
                with self.assertRaises(UnsupportedDwgError):
                    dwg_to_dxf(source, Path(directory) / 'out.dxf')
            self.assertFalse((Path(directory) / 'out.dxf').exists())


@unittest.skipUnless(os.environ.get('DWG2IMAGE_TEST_DIR'), 'set DWG2IMAGE_TEST_DIR for real DWGs')
class NativeDrawingTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(os.environ['DWG2IMAGE_TEST_DIR'])

    def test_mtext_source_fields_and_dxf_roundtrip(self):
        import ezdxf
        source = self.directory / '1 继电器.dwg'
        drawing = read_dwg(source)
        text = next(e for e in drawing.modelspace() if e['handle'] == '5D89')
        self.assertEqual(text['attributes']['text'], 'JZC4')
        self.assertEqual(text['attributes']['attachment_point'], 5)
        self.assertEqual(text['attributes']['char_height'], 8)
        self.assertAlmostEqual(text['attributes']['width'], 16.16181701881578)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'mtext.dxf'
            with patch('subprocess.run', side_effect=AssertionError('external execution')):
                dwg_to_dxf(source, output)
            document = ezdxf.readfile(output)
            texts = list(document.modelspace().query('MTEXT'))
            self.assertEqual(len(texts), 6)
            self.assertEqual(next(e for e in texts if e.text == 'JZC4').dxf.attachment_point, 5)
            self.assertFalse(document.audit().errors)

    def test_hatch_boundaries_and_simple_linetypes_survive_projection(self):
        import ezdxf
        for name, count in [('ABB-断路器', 1303), ('ATS NS250双电源转换开关', 8)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / 'hatch.dxf'
                dwg_to_dxf(self.directory / (name + '.dwg'), output)
                document = ezdxf.readfile(output)
                self.assertEqual(len(document.modelspace()), count)
                hatches = [e for e in document.entitydb.values() if e.dxftype() == 'HATCH']
                self.assertTrue(hatches)
                for hatch in hatches:
                    for boundary in hatch.paths:
                        for handle in boundary.source_boundary_objects:
                            self.assertIsNotNone(document.entitydb.get(handle))
                self.assertFalse(document.audit().errors)
                if name == 'ABB-断路器':
                    self.assertEqual(len(hatches), 12)
                    pattern = document.linetypes.get('EB_DASHDOT').pattern_tags.tags
                    self.assertEqual([t.value for t in pattern if t.code == 49], [30, -3, 3, -3])

    def test_native_full_modelspace_without_any_subprocess(self):
        import ezdxf
        from PIL import Image
        source = self.directory / '1 刀开关.dwg'
        expected = Counter(LINE=30, LWPOLYLINE=18, CIRCLE=11, ARC=2, TEXT=1)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'native.dxf'
            image = Path(directory) / 'native.png'
            with patch('subprocess.run', side_effect=AssertionError('external execution')):
                drawing = read_dwg(source)
                self.assertEqual(Counter(e['type'] for e in drawing.modelspace()), expected)
                self.assertEqual(drawing.unsupported_modelspace, {})
                self.assertEqual(dwg_to_dxf(str(source), str(output)), output)
                dwg_to_png(source, image, dpi=60)
            document = ezdxf.readfile(output)
            self.assertEqual(Counter(e.dxftype() for e in document.modelspace()), expected)
            self.assertFalse(document.audit().errors)
            with Image.open(image) as raster:
                self.assertTrue(any(low < high for low, high in raster.convert('RGB').getextrema()))
            with self.assertRaises(FileExistsError):
                dwg_to_dxf(source, output)

    def test_unsupported_modelspace_is_reported_and_never_silently_exported(self):
        drawing = read_dwg(self.directory / '1 空开.dwg')
        self.assertEqual(drawing.unsupported_modelspace, {'DIMENSION_LINEAR': 3})
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'missing-dimensions.dxf'
            with self.assertRaises(UnsupportedDwgError):
                dwg_to_dxf(self.directory / '1 空开.dwg', output)
            self.assertFalse(output.exists())
