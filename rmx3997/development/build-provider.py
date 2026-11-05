#!/usr/bin/python3
"""Build the OEM replacement against the parent's actual completed kernel.

No Image build, checkout, loading, installation or CRC edits. The normal
modpost consumes real complete-kernel exports and real shipping dependency
export CRCs; it rejects unexported symbols.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from elftools.elf.elffile import ELFFile

REPO = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-stage', type=Path, required=True)
    parser.add_argument('--freeze', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    stage = args.kernel_stage.resolve()
    record = json.loads((stage / 'build-execution.json').read_text())
    argv = json.loads((stage / 'build-argv.json').read_text())
    if record['exit_code'] or record['reason'] != 'completed' or record['argv'] != argv:
        raise ValueError('Requires actual successful parent Image/modules producer')
    if 'Image' not in argv or 'modules' not in argv or 'O=' + str(stage / 'out') not in argv:
        raise ValueError('Wrong kernel build path/targets')
    if not (stage / 'out/vmlinux').is_file() or not (stage / 'out/Module.symvers').is_file():
        raise ValueError('Incomplete parent build')
    freeze = json.loads(args.freeze.read_text())
    if hashlib.sha256((stage / 'out/.config').read_bytes()).hexdigest() != freeze['resolved_config_sha256']:
        raise ValueError('Completed kernel config differs from reviewed freeze')
    for path, expected in freeze['source_sha256'].items():
        if hashlib.sha256((REPO / path).read_bytes()).hexdigest() != expected:
            raise ValueError('Changed reviewed source: ' + path)
    env = json.loads((stage / 'build-environment.json').read_text())
    if not env['TMPDIR'].startswith('/home/build/.cache/codex-work/'):
        raise ValueError('Disk-backed task TMPDIR required')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    source = out / 'source'
    shutil.copytree(REPO / 'rmx3997/provider', source)
    state = json.loads((REPO / 'rmx3997/development/full-feature-20261104-state.json').read_text())
    dependencies = state['OEM_provider_boundary']['located_vendor_dlkm_modules']
    lines, provenance = [], []
    for name, info in dependencies.items():
        if name == 'oplus_bsp_hybridswap_zram': continue
        path = Path(info['path'])
        if hashlib.sha256(path.read_bytes()).hexdigest() != info['sha256']:
            raise ValueError('Shipping dependency changed: ' + name)
        provenance.append(info)
        with path.open('rb') as stream:
            elf = ELFFile(stream)
            symbols = {s.name: s for s in elf.get_section_by_name('.symtab').iter_symbols()}
            for symbol, entry in symbols.items():
                if not symbol.startswith('__crc_'): continue
                if entry['st_shndx'] != 'SHN_ABS': raise ValueError('Unexpected export CRC format')
                exported = symbol[6:]
                section = elf.get_section(symbols['__ksymtab_' + exported]['st_shndx'])
                kind = 'EXPORT_SYMBOL_GPL' if 'gpl' in section.name else 'EXPORT_SYMBOL'
                ns = symbols.get('__kstrtabns_' + exported)
                namespace = ''
                if ns and isinstance(ns['st_shndx'], int):
                    namespace = elf.get_section(ns['st_shndx']).data()[ns['st_value']:].split(b'\0', 1)[0].decode()
                lines.append(f"0x{entry['st_value']:08x}\t{exported}\t{name}\t{kind}\t{namespace}\n")
    extra = out / 'shipping-dependencies.symvers'
    extra.write_text(''.join(lines))
    (out / 'shipping-inputs.json').write_text(json.dumps(provenance, indent=2) + '\n')
    # Reuse the actual parent producer's compiler/toolchain argv; only replace
    # targets and add the external module and shipping dependency metadata.
    command = [item for item in argv if item not in ('Image', 'modules')]
    command += ['M=' + str(source / 'hybridswap_zram'), 'KBUILD_EXTRA_SYMBOLS=' + str(extra), 'modules']
    guarded = ['/usr/bin/python3', str(REPO / 'rmx3997/development/resource-guard.py'),
               '--log', str(out / 'build.log'), '--result', str(out / 'build-execution.json'), '--'] + command
    (out / 'build-command.json').write_text(json.dumps({'argv': guarded, 'cwd': str(REPO),
        'environment': env, 'parent_build_record_sha256': hashlib.sha256((stage / 'build-execution.json').read_bytes()).hexdigest()}, indent=2) + '\n')
    subprocess.run(guarded, cwd=REPO, env={**os.environ, **env}, check=True)
    module = source / 'hybridswap_zram/oplus_bsp_hybridswap_zram.ko'
    subprocess.run(['/usr/bin/python3', str(REPO / 'rmx3997/development/validate-provider-module.py'),
        '--module', str(module), '--kernel-symvers', str(stage / 'out/Module.symvers'),
        '--extra-symvers', str(extra), '--output', str(out / 'module-ABI.json')],
        cwd=REPO, env={**os.environ, **env}, check=True)
    shutil.copy2(module, out / module.name)


if __name__ == '__main__':
    main()
