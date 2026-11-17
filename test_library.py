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

    def test_cad_defaults_and_explicit_render_options(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "yellow.dxf"
            document = ezdxf.new()
            model = document.modelspace()
            model.add_line((0, 0), (0, 10), dxfattribs={"color": 2})
            model.add_line((0, 0), (10, 0), dxfattribs={"color": 2})
            document.saveas(source)
            default = dxf_to_png(source, Path(directory) / "default.png")
            with Image.open(default) as image:
                self.assertAlmostEqual(image.info["dpi"][0], 300, places=2)
                rgb = image.convert("RGB")
                self.assertEqual(rgb.getpixel((0, 0)), (33, 40, 48))
                row = [rgb.getpixel((x, rgb.height // 2)) for x in range(rgb.width)]
                self.assertGreaterEqual(row.count((255, 255, 0)), 2)
            explicit = dxf_to_png(source, Path(directory) / "white.png", dpi=100,
                                  background="#FFFFFF")
            with Image.open(explicit) as image:
                self.assertAlmostEqual(image.info["dpi"][0], 100, places=2)
                self.assertEqual(image.convert("RGB").getpixel((0, 0)), (255, 255, 255))

    def test_reject_wrong_format_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "wrong.jpg"
            with self.assertRaises(ValueError):
                dxf_to_png("missing.dxf", output)
            self.assertFalse(output.exists())


class NativeProjectionTests(unittest.TestCase):
    def test_closed_and_open_polylines_survive_dxf_projection(self):
        from dwg2image.native import NativeDrawing
        from dwg2image._native_export import to_dxf_document
        entities = []
        for index, flags in enumerate((1, 0, 129)):
            entities.append(dict(type='LWPOLYLINE', handle=str(index + 1), owner=None,
                                 layer_handle=10, linetype_handle=None, linetype_flag=0,
                                 mode=2, color=256, invisible=0, ltscale=1, lineweight=29,
                                 attributes={'flags': flags, '_points': [(0, 0, 0, 0, 0),
                                             (10, 0, 0, 0, 0), (10, 10, 0, 0, 0)]}))
        drawing = NativeDrawing(entities=entities,
            layers={10: {'name': '0', 'flags': 1008, 'color': 7, 'linetype_handle': 22}},
            unsupported_modelspace={}, object_count=3, styles={},
            linetypes={22: {'name': 'Continuous', 'description': '', 'length': 0,
                           'dashes': [], 'complex': False}}, blocks={}, unsupported_blocks={})
        document = to_dxf_document(drawing)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'polylines.dxf'
            document.saveas(output)
            restored = list(ezdxf.readfile(output).modelspace())
        self.assertEqual([entity.closed for entity in restored], [True, False, True])
        self.assertEqual([entity.dxf.flags for entity in restored], [1, 0, 129])
