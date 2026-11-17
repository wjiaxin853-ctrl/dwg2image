import struct
import tempfile
import unittest
from pathlib import Path
from dwg2image import inspect_dwg

class HeaderTests(unittest.TestCase):
    def inspect_bytes(self, data):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/'sample.dwg'; path.write_bytes(data)
            return inspect_dwg(path)

    def test_directory_and_file_bounds(self):
        data=bytearray(40);data[:6]=b'AC1015'
        struct.pack_into('<I',data,21,1)
        struct.pack_into('<BII',data,25,2,34,6)
        self.assertEqual(self.inspect_bytes(data)['r2000_section_directory'],[{'id':2,'offset':34,'size':6}])
        struct.pack_into('<I',data,30,7)
        with self.assertRaisesRegex(ValueError,'beyond file'): self.inspect_bytes(data)

    def test_truncated_directory(self):
        data=bytearray(25);data[:6]=b'AC1015';struct.pack_into('<I',data,21,10)
        with self.assertRaisesRegex(ValueError,'directory'):self.inspect_bytes(data)

    def test_unsupported_signature(self):
        with self.assertRaisesRegex(ValueError,'signature'):self.inspect_bytes(b'INVALID')

    def test_newer_header_does_not_claim_geometry(self):
        self.assertFalse(self.inspect_bytes(b'AC1032')['geometry_decoded'])

if __name__=='__main__':unittest.main()
