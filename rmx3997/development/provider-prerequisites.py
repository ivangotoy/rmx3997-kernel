#!/usr/bin/python3
"""Check retained OEM source closure before adapting the shipping provider.

This is an offline source/ELF prerequisite check, not an ABI or boot validator.
Exit 2 retains a concrete missing input; no stub headers or feature exclusions
are substituted. Requires the retained system Python with pyelftools.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

from elftools.elf.elffile import ELFFile


def inspect(tree_path, source_root, kernel_source, module):
    tree = json.loads(tree_path.read_text())
    if tree.get('truncated') is not False:
        raise ValueError('A complete retained OEM tree is required')
    prefix = 'vendor/oplus/kernel/mm/'
    entries = [e for e in tree['tree'] if e['type'] == 'blob' and
               e['path'].startswith((prefix + 'hybridswap_zram/',
                                      prefix + 'zram_opt/'))]
    if not entries:
        raise ValueError('No provider blobs in the supplied tree')
    invalid = []
    for entry in entries:
        path = source_root / entry['path']
        data = path.read_bytes() if path.is_file() else None
        actual = (hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data)
                  .hexdigest()) if data is not None else None
        if actual != entry['sha']:
            invalid.append({'path': entry['path'], 'expected': entry['sha'],
                            'actual': actual})
    if invalid:
        raise ValueError('Retained provider blobs differ: ' + repr(invalid))
    # These translation units are part of the shipping feature closure, as
    # evidenced by its ELF symbols/imports. Do not scan unused codec variants.
    units = ['zram_drv.c', 'zcomp.c', 'kcompressd.c',
             'hybridswap/hybridmain.c', 'hybridswap/hybridswap.c',
             'hybridswap/hybridswapd.c', 'hybridswap/ezr_empty.c',
             'hybridswap/display.c']
    indexed = {e['path']: e for e in tree['tree']}
    missing = []
    for unit in units:
        path = source_root / (prefix + 'hybridswap_zram/' + unit)
        for number, line in enumerate(path.read_text().splitlines(), 1):
            match = re.match(r'\s*#include\s+"([^"]+)"', line)
            if not match:
                continue
            target = (path.parent / match[1]).resolve()
            target.relative_to(source_root.resolve())  # reject escaped input
            if not target.is_file():
                relative = str(target.relative_to(source_root.resolve()))
                missing.append({'consumer': str(path.relative_to(source_root)),
                                'line': number, 'include': match[1],
                                'missing_path': relative,
                                'official_git_blob': indexed.get(relative, {}).get('sha')})
    # The shipping ELF imports MTK display notifiers. The initially unselected
    # display branch compiling successfully does not validate this interface.
    for header in ('mtk_panel_ext.h', 'mtk_disp_notify.h'):
        target = kernel_source / 'include/linux' / header
        if not target.is_file():
            missing.append({'consumer': prefix + 'hybridswap_zram/hybridswap/display.c',
                            'include': 'linux/' + header,
                            'missing_path': str(target),
                            'official_tree_candidates': [p for p in indexed
                                                         if p.endswith('/' + header)]})
    with module.open('rb') as stream:
        elf = ELFFile(stream)
        if elf['e_type'] != 'ET_REL' or elf['e_machine'] != 'EM_AARCH64':
            raise ValueError('Expected the retained ARM64 OEM module')
        symbols = list(elf.get_section_by_name('.symtab').iter_symbols())
        imports = sorted(s.name for s in symbols if s['st_shndx'] == 'SHN_UNDEF')
        exports = sorted(s.name[len('__ksymtab_'):] for s in symbols
                         if s.name.startswith('__ksymtab_') and
                         s.name != '__ksymtab_strings')
        modinfo = elf.get_section_by_name('.modinfo').data().decode().split('\0')
    return {
        'status': 'BLOCKED_SOURCE_CLOSURE' if missing else 'SOURCE_CLOSURE_ONLY',
        'verified_provider_blobs': len(entries),
        'source_tree_sha256': hashlib.sha256(tree_path.read_bytes()).hexdigest(),
        'missing_quoted_includes': missing,
        'shipping_module': str(module),
        'shipping_module_sha256': hashlib.sha256(module.read_bytes()).hexdigest(),
        'shipping_required_interfaces': [s for s in imports if s == 'oplus_read_mm_config'
                                         or s.startswith('mtk_disp_notifier_')],
        'shipping_exports': exports,
        'shipping_metadata': [s for s in modinfo if s.startswith(('depends=', 'vermagic=', 'name='))],
        'limits': 'Static source/ELF evidence only; feature flags/build recipe, full source correspondence, linked ABI, provider execution and rollback are not certified.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--kernel-source', type=Path, required=True)
    parser.add_argument('--module', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = inspect(args.tree, args.source_root, args.kernel_source, args.module)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(result['status'], 'verified blobs:', result['verified_provider_blobs'],
          'missing includes:', len(result['missing_quoted_includes']))
    return 2 if result['missing_quoted_includes'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
