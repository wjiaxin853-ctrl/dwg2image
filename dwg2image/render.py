"""Render DXF modelspace to a PNG without an external CAD application."""
from pathlib import Path
import tempfile
import shutil


def dxf_to_png(source: str | Path, destination: str | Path, *,
               dpi: int = 150, background: str = "#FFFFFF") -> Path:
    """Write a PNG, preserving existing outputs and removing failed staging.

    Only modelspace is rendered. Font substitution and unsupported CAD entities
    may affect appearance. Returns the destination Path.
    """
    import ezdxf
    from ezdxf.addons.drawing.matplotlib import qsave

    source, destination = Path(source), Path(destination)
    if destination.suffix.lower() != ".png":
        raise ValueError("destination must have a .png suffix")
    if not isinstance(dpi, int) or dpi <= 0:
        raise ValueError("dpi must be a positive integer")
    if destination.exists():
        raise FileExistsError(destination)
    document = ezdxf.readfile(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dwg2image-png-") as directory:
        rendered = Path(directory) / "drawing.png"
        qsave(document.modelspace(), rendered, dpi=dpi, bg=background, backend="agg")
        with destination.open("xb") as output:
            with rendered.open("rb") as image:
                shutil.copyfileobj(image, output)
    return destination
