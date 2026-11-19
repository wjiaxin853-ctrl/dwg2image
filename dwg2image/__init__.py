"""Pure-Python DWG decoding and rendering."""
from pathlib import Path
import tempfile

from ._conversion import inspect_dwg, inspect_dxf
from .render import dxf_to_png
from .native import read_dwg, NativeDrawing, UnsupportedDwgError
from ._native_bits import DwgFormatError

__all__ = ["dwg_to_dxf", "dxf_to_png", "dwg_to_png", "inspect_dwg", "inspect_dxf",
           "read_dwg", "NativeDrawing", "UnsupportedDwgError", "DwgFormatError"]


def dwg_to_dxf(source: str | Path, destination: str | Path) -> Path:
    """Write DXF with the independent Python decoder.

    Unsupported entities raise UnsupportedDwgError rather than being skipped.
    """
    from ._native_export import native_to_dxf
    return native_to_dxf(source, destination)


def dwg_to_png(source: str | Path, destination: str | Path, *,
               dpi: int = 300,
               background: str | None = None) -> Path:
    """Convert DWG to a modelspace PNG; temporary DXF is removed afterwards."""
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    with tempfile.TemporaryDirectory(prefix="dwg2image-render-") as directory:
        intermediate = Path(directory) / "drawing.dxf"
        dwg_to_dxf(source, intermediate)
        return dxf_to_png(intermediate, destination, dpi=dpi, background=background)
