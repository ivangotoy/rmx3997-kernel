#!/usr/bin/python3
"""Offline provider compatibility probe. Exit 2 means a demonstrated blocker.

This inspects retained firmware bytes; it neither loads modules nor creates a
ZRAM device. A successful probe is not feature, runtime, or parity acceptance.
Run with /usr/bin/python3 (the retained host has pyelftools there).
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(module):
    with module.open('rb') as stream:
        elf = ELFFile(stream)
        if elf['e_type'] != 'ET_REL' or elf['e_machine'] != 'EM_AARCH64':
            raise ValueError('Expected the retained ARM64 relocatable module')
        symbols = list(elf.get_section_by_name('.symtab').iter_symbols())
        by_name = {s.name: s for s in symbols}
        cls = by_name['zram_control_class']
        name_targets = []
        init_calls = []
        init = by_name['init_module']
        for section in elf.iter_sections():
            if not isinstance(section, RelocationSection):
                continue
            table = elf.get_section(section['sh_link'])
            for relocation in section.iter_relocations():
                symbol = table.get_symbol(relocation['r_info_sym'])
                if (section['sh_info'] == cls['st_shndx'] and
                        relocation['r_offset'] == cls['st_value']):
                    target = elf.get_section(symbol['st_shndx'])
                    offset = symbol['st_value'] + relocation['r_addend']
                    name_targets.append({
                        'section': target.name, 'section_offset': offset,
                        'file_offset': target['sh_offset'] + offset,
                        'name': target.data()[offset:].split(b'\0', 1)[0].decode(),
                    })
                if (section['sh_info'] == init['st_shndx'] and
                        init['st_value'] <= relocation['r_offset'] <
                        init['st_value'] + init['st_size'] and
                        relocation['r_info_type'] == 283):  # R_AARCH64_CALL26
                    init_calls.append({'section_offset': relocation['r_offset'],
                                       'symbol': symbol.name})
        exports = sorted(s.name[len('__ksymtab_'):] for s in symbols
                         if s.name.startswith('__ksymtab_') and
                         s.name != '__ksymtab_strings')
        functions = {}
        for name in ('init_module', 'comp_algorithm_store', 'zcomp_compress',
                     'zcomp_decompress'):
            symbol = by_name[name]
            section = elf.get_section(symbol['st_shndx'])
            start, size = symbol['st_value'], symbol['st_size']
            functions[name] = {'section': section.name, 'section_offset': start,
                               'size': size,
                               'sha256': hashlib.sha256(section.data()[start:start + size]).hexdigest()}
        return {
            'class_name_relocations': name_targets, 'init_direct_calls': init_calls,
            'functions': functions, 'exports': exports,
            'recompression_symbols': sorted(s.name for s in symbols
                                           if re.search(r'recomp|recompress', s.name)),
            'device_attributes': sorted(s.name for s in symbols
                                        if s.name.startswith('dev_attr_')),
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--disassembly', type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    inventory = args.evidence_root / 'module-inventory.json'
    entries = json.loads(inventory.read_text())
    entry = next(e for e in entries if e['name'] == 'oplus_bsp_hybridswap_zram')
    module = Path(entry['local_path'])
    if digest(module) != entry['sha256']:
        raise ValueError('Retained firmware identity changed')
    observed = inspect(module)
    source = repo / 'drivers/block/zram/zram_drv.c'
    generic = source.read_text()
    name = re.search(r'static struct class zram_control_class = \{\s*\.name\s*=\s*"([^"]+)"', generic)[1]
    class_conflict = any(t['name'] == name for t in observed['class_name_relocations'])
    class_call = any(c['symbol'] == '__class_register' for c in observed['init_direct_calls'])
    capture = args.evidence_root.parent / 'kernel-compatibility-20261103/device-readonly.txt'
    loaded = bool(re.search(r'^oplus_bsp_hybridswap_zram .* Live ', capture.read_text(), re.M))
    dependants = [e['name'] for e in entries
                  if 'oplus_bsp_hybridswap_zram' in e['depends']]
    toolchain = Path(json.loads((repo / 'rmx3997/build-environment.json').read_text())['PATH'].split(':')[0])
    argv = [str(toolchain / 'llvm-objdump'), '-dr',
            '--disassemble-symbols=init_module,comp_algorithm_store,zcomp_compress,zcomp_decompress',
            str(module)]
    # Exclusive files preserve previous runs; selected functions bound the log.
    with args.disassembly.open('xb') as log:
        subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT, check=True)
    blocked = class_conflict and class_call and loaded
    record = {
        'scope': 'Static ELF relocations/code and retained stock capture; no new device or kernel execution',
        'module': {'path': str(module), 'sha256': digest(module)},
        'inventory': {'path': str(inventory), 'sha256': digest(inventory)},
        'stock_capture': {'path': str(capture), 'sha256': digest(capture), 'provider_loaded': loaded},
        'generic_source': {'path': str(source), 'sha256': digest(source), 'class_name': name},
        'observed': observed, 'shipping_dependants': dependants,
        'disassembly': {'argv': argv, 'path': str(args.disassembly), 'sha256': digest(args.disassembly)},
        'status': 'BLOCKED_PROVIDER_COEXISTENCE' if blocked else 'UNRESOLVED',
        'reason': 'Generic built-in ZRAM and the loaded OEM provider both register zram-control. '
                  'Generic multi-compression cannot extend this separately compiled OEM implementation. '
                  'The OEM exports contain no zcomp/zram compressor replacement interface.',
        'required_resolution': 'A reviewed port against exact OEM provider source preserving its exports, '
                               'physical layouts and hybrid-swap semantics, or an independently evidenced '
                               'safe extension of this actual provider. Source availability has not been established.',
        'limits': 'Absence of named recompression symbols is bounded to this ELF symbol table. '
                  'It does not prove that no possible extension can ever be engineered. '
                  'No module replacement, unloading, crypto interception or device writes were attempted.',
        'full_feature_parity': False,
    }
    with args.output.open('x') as output:
        json.dump(record, output, indent=2)
        output.write('\n')
    print(record['status'])
    return 2 if blocked else 1


if __name__ == '__main__':
    raise SystemExit(main())
