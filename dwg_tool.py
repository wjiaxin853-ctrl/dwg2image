"""DWG inspection and an explicit ODA-backed DXF conversion prototype.

This is not an independent DWG geometry decoder. No shell interpolation is used.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import tempfile
import uuid


def inspect_dwg(path):
    data = path.read_bytes()
    signature = data[:6].decode('ascii', errors='replace')
    result = {'path': str(path.resolve()), 'sha256': hashlib.sha256(data).hexdigest(),
              'bytes': len(data), 'signature': signature, 'geometry_decoded': False}
    if signature == 'AC1015':
        if len(data) < 25:
            raise ValueError('truncated AC1015 header')
        count = struct.unpack_from('<I', data, 0x15)[0]
        if count > (len(data)-25)//9:
            raise ValueError('section directory extends beyond file')
        sections = []
        for i in range(count):
            ident, offset, size = struct.unpack_from('<BII', data, 25+9*i)
            if offset+size > len(data):
                raise ValueError(f'section {ident} extends beyond file')
            sections.append({'id': ident, 'offset': offset, 'size': size})
        result['r2000_section_directory'] = sections
    elif signature != 'AC1032':
        raise ValueError(f'unexamined DWG signature: {signature!r}')
    return result


def convert(source, destination, appdir, image=None, timeout=300):
    """Convert one file in fresh staging, so stale output cannot pass validation."""
    inspect_dwg(source)
    if destination.exists():
        raise FileExistsError(f'refusing to overwrite {destination}')
    binary = appdir / 'usr/bin/ODAFileConverter'
    if not binary.is_file():
        raise FileNotFoundError(binary)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='dwg2image-') as temp:
        root = Path(temp); (root/'in').mkdir(); (root/'out').mkdir()
        shutil.copy2(source, root/'in'/source.name)
        args = ['ACAD2018', 'DXF', '0', '1', '*.dwg']
        if image:
            container_name = 'dwg2image-' + uuid.uuid4().hex
            cmd = ['docker', 'run', '--rm', '--name', container_name, '--network=none', '--platform', 'linux/amd64',
                   '--ulimit', 'core=0', '-e', 'QT_QPA_PLATFORM=xcb',
                   '-e', 'LD_LIBRARY_PATH=/oda/usr/bin:/oda/usr/lib',
                   '-e', 'QT_PLUGIN_PATH=/oda/usr/plugins',
                   '-v', f'{appdir.resolve()}:/oda:ro', '-v', f'{root.resolve()}:/job',
                   '-v', f'{Path(__file__).resolve().parent / "run_headless.sh"}:/run_headless.sh:ro',
                   image, 'sh', '/run_headless.sh', '/oda/usr/bin/ODAFileConverter', '/job/in', '/job/out', *args]
            env = None
        else:
            if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'AMD64'):
                raise RuntimeError('ODA requires Linux x86-64; use --docker-image with a prepared image')
            env = dict(os.environ, QT_QPA_PLATFORM='xcb',
                       LD_LIBRARY_PATH=f'{appdir.resolve()}/usr/bin:{appdir.resolve()}/usr/lib',
                       QT_PLUGIN_PATH=f'{appdir.resolve()}/usr/plugins')
            cmd = ['xvfb-run', '-a', str(binary.resolve()), str(root/'in'), str(root/'out'), *args]
        try:
            completed = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
        finally:
            if image:
                subprocess.run(['docker', 'rm', '-f', container_name], capture_output=True, timeout=30)
        if completed.returncode:
            raise RuntimeError(f'ODA exit {completed.returncode}: {completed.stderr}\n{completed.stdout}')
        candidates = [f for f in (root/'out').iterdir() if f.suffix.lower()=='.dxf']
        if len(candidates)!=1:
            raise RuntimeError(f'expected one fresh DXF, found {len(candidates)}: {completed.stdout}')
        report = inspect_dxf(candidates[0])
        with destination.open('xb') as output:
            with candidates[0].open('rb') as converted:
                shutil.copyfileobj(converted, output)
        report.update(output=str(destination.resolve()), backend='closed-source ODA',
                      source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
        return report


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
    s.add_argument('--appdir', type=Path, required=True);s.add_argument('--docker-image');s.add_argument('--timeout', type=int, default=300)
    a=p.parse_args()
    if a.command=='inspect': result=inspect_dwg(a.path)
    elif a.command=='check-dxf': result=inspect_dxf(a.path)
    else: result=convert(a.path,a.output,a.appdir,a.docker_image,a.timeout)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__=='__main__':
    main()
