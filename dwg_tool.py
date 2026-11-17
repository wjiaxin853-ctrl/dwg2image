"""Compatibility entry point; prefer the installed dwg2image command."""
from dwg2image._conversion import convert, inspect_dwg, inspect_dxf, main

if __name__ == "__main__":
    main()
