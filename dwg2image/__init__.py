"""Pure-Python DWG decoding and rendering."""
from pathlib import Path

from ._conversion import inspect_dwg, inspect_dxf
from .render import dxf_to_png
from .native import read_dwg, NativeDrawing, UnsupportedDwgError
from ._native_bits import DwgFormatError

__all__ = ["dwg_to_dxf", "dxf_to_png", "dwg_to_png", "inspect_dwg", "inspect_dxf",
           "read_dwg", "NativeDrawing", "UnsupportedDwgError", "DwgFormatError"]


def dwg_to_dxf(source: str | Path, destination: str | Path, *, strict: bool = True) -> Path:
    """Write DXF with the independent Python decoder.

    Unsupported entities raise UnsupportedDwgError in strict mode; with
    ``strict=False`` they are omitted and reported by ``read_dwg()`` counters.
    """
    from ._native_export import native_to_dxf
    return native_to_dxf(source, destination, strict=strict)


def dwg_to_png(source: str | Path, destination: str | Path, *,
               dpi: int = 300,
               background: str | None = None,
               strict: bool = True) -> Path:
    """Convert DWG to a modelspace PNG.

    ``strict=False`` renders the decodable subset; see ``read_dwg()`` for the
    unsupported-entity counters.
    """
    from ._native_export import to_dxf_document
    from .render import _png_destination, _render_png

    destination = _png_destination(destination, dpi)
    return _render_png(to_dxf_document(read_dwg(source), strict=strict),
                       destination, dpi, background)
