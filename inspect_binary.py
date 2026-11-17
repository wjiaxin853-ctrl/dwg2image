"""Static ELF evidence, no target execution. Requires pyelftools and capstone."""
import argparse
import hashlib
import json
from pathlib import Path
from elftools.elf.elffile import ELFFile
from capstone import Cs, CS_ARCH_X86, CS_MODE_64


def inspect(path):
    with path.open('rb') as stream:
        elf = ELFFile(stream)
        symbols = list(elf.get_section_by_name('.symtab').iter_symbols())
        names = {s['st_value']: s.name for s in symbols if s['st_value']}
        plt = elf.get_section_by_name('.plt')
        rel = elf.get_section_by_name('.rela.plt')
        if plt and rel:
            dyn = elf.get_section(rel['sh_link'])
            for i, r in enumerate(rel.iter_relocations()):
                names[plt['sh_addr'] + 16*(i+1)] = dyn.get_symbol(r['r_info_sym']).name+'@plt'
        text = elf.get_section_by_name('.text')
        functions = []
        md = Cs(CS_ARCH_X86, CS_MODE_64)
        for s in symbols:
            if s['st_info']['type'] != 'STT_FUNC' or not s['st_size']:
                continue
            if not (s.name == 'main' or ('CConvertor' in s.name and any(t in s.name for t in ('convertFile', 'startConvertion', 'initEv'))) or ('Compressor' in s.name and 'decompress' in s.name)):
                continue
            start = s['st_value'] - text['sh_addr']
            instructions = []
            for ins in md.disasm(text.data()[start:start+s['st_size']], s['st_value']):
                target = None
                if ins.mnemonic in ('call', 'jmp') and ins.op_str.startswith('0x'):
                    target = names.get(int(ins.op_str, 16))
                instructions.append({'address':hex(ins.address), 'instruction':ins.mnemonic+' '+ins.op_str, 'target_symbol':target})
            functions.append({'symbol':s.name, 'address':hex(s['st_value']), 'size':s['st_size'], 'instructions':instructions})
        return {'path':str(path.resolve()), 'sha256':hashlib.sha256(path.read_bytes()).hexdigest(), 'machine':elf['e_machine'], 'functions':functions}

if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('binary', type=Path);a=p.parse_args()
    print(json.dumps(inspect(a.binary), ensure_ascii=False, indent=2))
