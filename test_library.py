"""Public API regressions with a real DXF and real raster output."""
from pathlib import Path
import tempfile
import unittest

import ezdxf
from PIL import Image
from dwg2image import dxf_to_png


class RenderingTests(unittest.TestCase):
    def test_real_png_and_preserve_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "sample.dxf"
            output = Path(directory) / "图纸.png"
            document = ezdxf.new()
            document.modelspace().add_circle((0, 0), radius=5)
            document.modelspace().add_line((0, 0), (5, 5))
            document.saveas(source)
            self.assertEqual(dxf_to_png(str(source), str(output), dpi=60), output)
            with Image.open(output) as image:
                self.assertEqual(image.format, "PNG")
                extrema = image.convert("RGB").getextrema()
                self.assertTrue(any(low < high for low, high in extrema))
            before = output.read_bytes()
            with self.assertRaises(FileExistsError):
                dxf_to_png(source, output)
            self.assertEqual(output.read_bytes(), before)

    def test_reject_wrong_format_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "wrong.jpg"
            with self.assertRaises(ValueError):
                dxf_to_png("missing.dxf", output)
            self.assertFalse(output.exists())
