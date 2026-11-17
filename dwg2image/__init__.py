"""DWG decoding and rendering, with optional ODA compatibility conversion."""
from pathlib import Path
import tempfile

from ._conversion import convert, inspect_dwg, inspect_dxf
from .render import dxf_to_png
from .native import read_dwg, NativeDrawing, UnsupportedDwgError
from ._native_bits import DwgFormatError

__all__ = ["dwg_to_dxf", "dxf_to_png", "dwg_to_png", "inspect_dwg", "inspect_dxf",
           "read_dwg", "NativeDrawing", "UnsupportedDwgError", "DwgFormatError"]


def dwg_to_dxf(source: str | Path, destination: str | Path, *,
               appdir: str | Path | None = None, docker_image: str | None = None,
               timeout: float = 300) -> Path:
    """Write DXF with the independent AC1015 decoder by default.

    Unsupported entities raise UnsupportedDwgError rather than being skipped.
    Supplying appdir explicitly selects the legacy external ODA converter.
    """
    if appdir is None:
        if docker_image is not None:
            raise ValueError("docker_image requires an explicit ODA appdir")
        from ._native_export import native_to_dxf
        return native_to_dxf(source, destination)
    convert(source, destination, appdir, image=docker_image, timeout=timeout)
    return Path(destination)


def dwg_to_png(source: str | Path, destination: str | Path, *,
               appdir: str | Path | None = None, docker_image: str | None = None,
               timeout: float = 300, dpi: int = 150,
               background: str = "#FFFFFF") -> Path:
    """Convert DWG to a modelspace PNG; temporary DXF is removed afterwards."""
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    with tempfile.TemporaryDirectory(prefix="dwg2image-render-") as directory:
        intermediate = Path(directory) / "drawing.dxf"
        dwg_to_dxf(source, intermediate, appdir=appdir,
                   docker_image=docker_image, timeout=timeout)
        return dxf_to_png(intermediate, destination, dpi=dpi, background=background)
