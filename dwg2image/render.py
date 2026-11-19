"""Render DXF modelspace to a PNG without an external CAD application."""
from pathlib import Path
import tempfile
import shutil


def dxf_to_png(source: str | Path, destination: str | Path, *,
               dpi: int = 300, background: str | None = None) -> Path:
    """Write a PNG, preserving existing outputs and removing failed staging.

    Default background follows the CAD layout; an explicit color is preserved.
    Only modelspace is rendered. Font substitution and unsupported CAD entities
    may affect appearance. Returns the destination Path.
    """
    import ezdxf
    destination = _png_destination(destination, dpi)
    return _render_png(ezdxf.readfile(Path(source)), destination, dpi, background)


def _png_destination(destination, dpi):
    destination = Path(destination)
    if destination.suffix.lower() != ".png":
        raise ValueError("destination must have a .png suffix")
    if not isinstance(dpi, int) or dpi <= 0:
        raise ValueError("dpi must be a positive integer")
    if destination.exists():
        raise FileExistsError(destination)
    return destination


def _render_png(document, destination, dpi, background):
    from ezdxf.addons.drawing.matplotlib import qsave
    from ezdxf.addons.drawing.config import Configuration

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwg2image-png-") as directory:
        rendered = Path(directory) / "drawing.png"
        # Keep a physical minimum stroke; qsave otherwise uses one output pixel,
        # making CAD hairlines too thin at high DPI. 0.72 pt is 1 px at 100 DPI.
        config = Configuration(min_lineweight=0.72)
        qsave(document.modelspace(), rendered, dpi=dpi, bg=background,
              backend="agg", config=config)
        with destination.open("xb") as output:
            with rendered.open("rb") as image:
                shutil.copyfileobj(image, output)
    return destination
