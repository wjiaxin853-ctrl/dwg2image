"""DWG conversion requires an external ODA installation; DXF rendering is local."""
from pathlib import Path
import tempfile

from ._conversion import convert, inspect_dwg, inspect_dxf
from .render import dxf_to_png

__all__ = ["dwg_to_dxf", "dxf_to_png", "dwg_to_png", "inspect_dwg", "inspect_dxf"]


def dwg_to_dxf(source: str | Path, destination: str | Path, *,
               appdir: str | Path, docker_image: str | None = None,
               timeout: float = 300) -> Path:
    """Write a fresh DXF using ODA. Existing destinations are never overwritten.

    appdir is an extracted Linux x86-64 ODA AppImage directory. On other
    platforms, supply a prepared Linux x86-64 docker_image as well.
    Raises FileExistsError, OSError, ValueError, RuntimeError or TimeoutExpired.
    """
    convert(source, destination, appdir, image=docker_image, timeout=timeout)
    return Path(destination)


def dwg_to_png(source: str | Path, destination: str | Path, *,
               appdir: str | Path, docker_image: str | None = None,
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
