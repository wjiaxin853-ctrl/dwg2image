"""DWG and DXF inspection and pure-Python conversion CLI."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def inspect_dwg(path):
    path = Path(path)
    data = path.read_bytes()
    signature = data[:6].decode('ascii', errors='replace')
    result = {'path': str(path.resolve()), 'sha256': hashlib.sha256(data).hexdigest(),
              'bytes': len(data), 'signature': signature, 'geometry_decoded': False}
    if signature == 'AC1015':
        from .native import _sections
        result['r2000_section_directory'] = [
            {'id': ident, 'offset': offset, 'size': size}
            for ident, (offset, size) in _sections(data).items()
        ]
    elif signature not in ('AC1018', 'AC1021', 'AC1024', 'AC1027', 'AC1032'):
        raise ValueError(f'unexamined DWG signature: {signature!r}')
    return result


def inspect_dxf(path):
    import ezdxf
    doc = ezdxf.readfile(path)
    audit = doc.audit()
    return {'dxf_version': doc.dxfversion, 'modelspace_entities': dict(Counter(e.dxftype() for e in doc.modelspace())),
            'blocks': len(doc.blocks), 'layers': len(doc.layers), 'audit_errors': len(audit.errors),
            'audit_fixes': len(audit.fixes), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'limitation': 'Readable DXF does not prove geometric fidelity to the DWG.'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command', required=True)
    for name in ('inspect', 'check-dxf'):
        s=sub.add_parser(name);s.add_argument('path', type=Path)
    s=sub.add_parser('convert');s.add_argument('path', type=Path);s.add_argument('output', type=Path)
    a=p.parse_args()
    if a.command=='inspect': result=inspect_dwg(a.path)
    elif a.command=='check-dxf': result=inspect_dxf(a.path)
    else:
        from . import dwg_to_dxf
        output = dwg_to_dxf(a.path, a.output)
        result = inspect_dxf(output)
        result.update(output=str(output.resolve()), backend='independent Python decoder')
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__=='__main__':
    main()
