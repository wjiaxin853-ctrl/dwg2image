"""Real sample checks for the isolated AC1015 dimension payload reader."""
import os
from pathlib import Path
import unittest

from dwg2image._native_dimension import decode_dimension
from dwg2image.native import _common, _object, _object_map, _sections


@unittest.skipUnless(os.environ.get('DWG2IMAGE_TEST_DIR'), 'set DWG2IMAGE_TEST_DIR')
class DimensionPayloadTests(unittest.TestCase):
    def test_sample_payloads_end_at_declared_boundary(self):
        counts = {'1 空开.dwg': 3, '1 塑壳.dwg': 314, '1 软启动.dwg': 128}
        for name, expected in counts.items():
            with self.subTest(name=name):
                data = (Path(os.environ['DWG2IMAGE_TEST_DIR']) / name).read_bytes()
                sections = _sections(data)
                found = 0
                for handle, address in _object_map(data, sections[2]):
                    kind, reader, endbit = _object(data, address, handle)
                    if kind not in (20, 21, 22, 26):
                        continue
                    _common(reader)
                    decode_dimension(kind, reader)
                    self.assertEqual(reader.pos, endbit, (name, handle, kind))
                    found += 1
                self.assertEqual(found, expected)

    def test_knife_switch_linear_dimension_coordinates(self):
        data = (Path(os.environ['DWG2IMAGE_TEST_DIR']) / '1 空开.dwg').read_bytes()
        sections = _sections(data)
        found = {}
        for handle, address in _object_map(data, sections[2]):
            kind, reader, endbit = _object(data, address, handle)
            if kind == 21 and handle in (0x38FA, 0x39C1, 0x8B6B):
                _common(reader)
                found[handle] = decode_dimension(kind, reader)
        self.assertEqual(set(found), {0x38FA, 0x39C1, 0x8B6B})
        first = found[0x38FA]
        # Fresh ODA DXF: handle 38FA, geometry *D4, ISO-25.
        self.assertAlmostEqual(first['actual_measurement'], 119.99999415)
        self.assertAlmostEqual(first['text_midpoint'][0], 1882.561019211667)
        self.assertAlmostEqual(first['defpoint'][1], 1411.219143465688)
        self.assertAlmostEqual(first['defpoint2'][1], 1531.219137615688)
        self.assertAlmostEqual(first['defpoint3'][1], 1411.219143465688)
        self.assertAlmostEqual(first['dim_rotation'], 90.0)


if __name__ == '__main__':
    unittest.main()
