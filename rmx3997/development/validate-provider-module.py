#!/usr/bin/python3
"""Check real provider ELF ABI against retained shipping consumers/exports.

Component metadata is not a substitute for the parent's final linked Image,
BTF, strict GKI export policy, all463 or actual module-load validation.
"""
import argparse
import hashlib
import json
from pathlib import Path

from elftools.elf.elffile import ELFFile

OEM = Path('/home/build/Downloads/rea-lk-analysis/oem-module-compatibility-20261103')
ORIGINAL = OEM / 'filesystems/vendor_dlkm_b/lib/modules/oplus_bsp_hybridswap_zram.ko'


def inspect(path):
    with path.open('rb') as stream:
        elf = ELFFile(stream)
        if elf['e_machine'] != 'EM_AARCH64' or elf['e_type'] != 'ET_REL':
            raise ValueError('Expected real ARM64 .ko')
        symbols = {s.name: s for s in elf.get_section_by_name('.symtab').iter_symbols()}
        exports = {name[6:]: symbol['st_value'] for name, symbol in symbols.items()
                   if name.startswith('__crc_') and symbol['st_shndx'] == 'SHN_ABS'}
        raw = elf.get_section_by_name('__versions').data()
        versions = {raw[i+8:i+64].split(b'\0', 1)[0].decode():
                    int.from_bytes(raw[i:i+8], 'little') for i in range(0, len(raw), 64)}
        undefined = sorted(name for name, s in symbols.items() if s['st_shndx'] == 'SHN_UNDEF' and name)
        modinfo = elf.get_section_by_name('.modinfo').data().decode().split('\0')
        return {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'exports': exports,
                'versions': versions, 'undefined': undefined,
                'metadata': [s for s in modinfo if s.startswith(('vermagic=', 'depends=', 'import_ns='))],
                'unloadable': 'cleanup_module' in symbols, 'BTF': elf.get_section_by_name('.BTF') is not None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module', type=Path, required=True)
    parser.add_argument('--kernel-symvers', type=Path, required=True)
    parser.add_argument('--extra-symvers', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    old, new = inspect(ORIGINAL), inspect(args.module)
    if old['sha256'] != '66c8904aca7e43f54cd4c7ed7c7a8df358031acd6885f569fefb2a656e17d302':
        raise ValueError('Original changed')
    if new['exports'] != old['exports'] or len(new['exports']) != 13:
        raise ValueError('Shipping provider export ABI changed')
    available = {}
    for path in (args.kernel_symvers, args.extra_symvers):
        for line in path.read_text().splitlines():
            fields = line.split()
            available[fields[1]] = int(fields[0], 16)
    mismatches = {name: (crc, available.get(name)) for name, crc in new['versions'].items()
                  if available.get(name) != crc}
    if mismatches:
        raise ValueError('Real component import CRC mismatch: ' + repr(mismatches))
    inventory_path = OEM / 'module-inventory.json'
    inventory = [m for m in json.loads(inventory_path.read_text())
                 if not m['path'].startswith('dump_init_boot_b:')]
    if len(inventory) != 489 or len({m['sha256'] for m in inventory}) != 463:
        raise ValueError('Shipping463 inventory differs')
    consumers = []
    for module in inventory:
        matches = []
        requirements = {item['symbol']: item for item in module['imports']}
        for name, crc in module['versions'].items():
            requirements.setdefault(name, {'symbol': name, 'crc': crc})
        for item in requirements.values():
            if item['symbol'] in new['exports']:
                expected = item.get('crc')
                actual = new['exports'][item['symbol']]
                if isinstance(expected, str): expected = int(expected, 16)
                if expected != actual:
                    raise ValueError('Consumer CRC differs: ' + module['path'])
                matches.append(item['symbol'])
        if matches: consumers.append({'module': module['path'], 'imports': matches})
    record = {'status': 'PASS component ELF ABI only', 'original': old, 'candidate': new,
        'all463_inventory_sha256': hashlib.sha256(inventory_path.read_bytes()).hexdigest(),
        'inventory_count': 489, 'unique_module_count': 463, 'provider_consumers': consumers,
        'new_imports_since_shipping': sorted(set(new['versions']) - set(old['versions'])),
        'limits': 'Component link uses retained real core symvers plus actual new cgroup object CRC and shipping dependency exports. New full Image/export policy/BTF/runtime gates remain; no loader/CRC overrides.'}
    args.output.write_text(json.dumps(record, indent=2) + '\n')
    print(record['status'], 'exports=13 consumers=' + str(len(consumers)))


if __name__ == '__main__':
    main()
