#!/usr/bin/python3
"""Stage a provider preinit payload after the parent Image/module acceptance.

Creates disk artifacts only. Does not install, change init_boot/vendor_dlkm,
publish a ZIP or certify phone boot. The boot-only installer remains the owner
of boot_b backup/write/readback/rollback. Its release constants must be bound to
the same accepted Image by the final packager.
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
TASK = Path('/home/build/.cache/codex-work/rmx3997-full-features-20261104')
ORIGINAL = '66c8904aca7e43f54cd4c7ed7c7a8df358031acd6885f569fefb2a656e17d302'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exported_crc(path):
    with path.open('rb') as stream:
        elf = ELFFile(stream)
        return {s.name[6:]: s['st_value'] for s in
                elf.get_section_by_name('.symtab').iter_symbols()
                if s.name.startswith('__crc_') and s['st_shndx'] == 'SHN_ABS'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', type=Path, required=True)
    parser.add_argument('--module', type=Path, required=True)
    parser.add_argument('--acceptance', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not os.environ.get('TMPDIR', '').startswith(str(TASK)):
        raise ValueError('Retained ext4 task TMPDIR required')
    stage = args.stage.resolve()
    image = stage / 'out/arch/arm64/boot/Image'
    vmlinux = stage / 'out/vmlinux'
    build = json.loads((stage / 'build-execution.json').read_text())
    if build['exit_code'] or build['reason'] != 'completed':
        raise ValueError('No accepted successful Image build')
    if build['argv'] != json.loads((stage / 'build-argv.json').read_text()):
        raise ValueError('Build argv mismatch')
    if 'Image' not in build['argv'] or 'modules' not in build['argv']:
        raise ValueError('Wrong producer')
    acceptance = json.loads(args.acceptance.read_text())
    for key, path in [('Image_sha256', image), ('vmlinux_sha256', vmlinux),
                      ('provider_sha256', args.module)]:
        if acceptance[key] != sha(path):
            raise ValueError('Acceptance input differs: ' + key)
    for key in ('linked_ABI', 'all463', 'F2FS', 'BTF'):
        if acceptance[key] != 'PASS':
            raise ValueError('Unresolved acceptance: ' + key)
    state = json.loads((REPO / 'rmx3997/development/full-feature-20261104-state.json').read_text())
    modules = state['OEM_provider_boundary']['located_vendor_dlkm_modules']
    original = Path(modules['oplus_bsp_hybridswap_zram']['path'])
    if sha(original) != ORIGINAL or exported_crc(original) != exported_crc(args.module):
        raise ValueError('Original or replacement provider export ABI differs')
    with vmlinux.open('rb') as stream:
        notes = ELFFile(stream).get_section_by_name('.notes').data()
    notes_sha = hashlib.sha256(notes).hexdigest()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    order = state['OEM_provider_boundary']['dependency_load_order']
    rows = []
    dependency_files = {}
    for name in order:
        info = modules[name]
        if name == 'oplus_bsp_hybridswap_zram':
            path, digest = './provider.ko', sha(args.module)
        else:
            source = Path(info['path'])
            if sha(source) != info['sha256']:
                raise ValueError('Shipping dependency changed: ' + name)
            # First-stage ramdisk module paths may disappear after switch_root.
            # Package exact original bytes alongside the loader, even when the
            # kernel already has that dependency loaded and will skip it.
            path, digest = './' + source.name, info['sha256']
            shutil.copy2(source, out / source.name)
            dependency_files[source.name] = digest
        rows.append('{' + ', '.join(json.dumps(x) for x in (path, name, digest)) + '}')
    header = '#define PROVIDER_KERNEL_NOTES_SHA256 ' + json.dumps(notes_sha) + '\n'
    header += 'static const struct provider_input provider_inputs[] = {\n' + ',\n'.join(rows) + '\n};\n'
    (out / 'provider-inputs.h').write_text(header)
    (out / 'provider-dependencies.sha256').write_text(''.join(
        digest + '  ' + name + '\n' for name, digest in sorted(dependency_files.items())))
    env = json.loads((stage / 'build-environment.json').read_text())
    compiler = env['PATH'].split(':')[0] + '/clang'
    sysroot = '/home/build/Downloads/rea-lk-analysis/rmx3997-custom-gki-build/kernel/prebuilts/ndk-r23/toolchains/llvm/prebuilt/linux-x86_64/sysroot'
    argv = [compiler, '--target=aarch64-linux-android31', '--sysroot=' + sysroot,
            '-static', '-O2', '-Wall', '-Wextra', '-Werror', '-fuse-ld=lld', '--rtlib=compiler-rt',
            '-I' + str(out), str(REPO / 'rmx3997/provider/preinit-loader.c'),
            '-o', str(out / 'provider-loader')]
    guarded = ['/usr/bin/python3', str(REPO / 'rmx3997/development/resource-guard.py'),
               '--log', str(out / 'loader-build.log'), '--result', str(out / 'loader-build.json'), '--'] + argv
    (out / 'loader-command.json').write_text(json.dumps({'argv': guarded, 'cwd': str(REPO), 'environment': env}, indent=2) + '\n')
    subprocess.run(guarded, env={**os.environ, **env}, check=True)
    for source, name in [(args.module, 'provider.ko'), (original, 'original-provider.ko'),
                         (REPO / 'rmx3997/provider/preinit.conf', 'preinit.conf')]:
        shutil.copy2(source, out / name)
    for name in ('provider-install-entry.sh', 'provider-transaction.sh', 'provider-android.sh'):
        shutil.copy2(REPO / 'rmx3997/provider' / name, out / name)
    release = {'PROVIDER_MODULE_SHA256': sha(out / 'provider.ko'),
               'PROVIDER_LOADER_SHA256': sha(out / 'provider-loader'),
               'PROVIDER_CONF_SHA256': sha(out / 'preinit.conf')}
    release['PROVIDER_DEPS_SHA256'] = sha(out / 'provider-dependencies.sha256')
    (out / 'provider-release.sh').write_text(''.join(key + '=' + value + '\n' for key, value in release.items()))
    (out / 'manifest.json').write_text(json.dumps({'Image_sha256': sha(image),
        'vmlinux_sha256': sha(vmlinux), 'notes_sha256': notes_sha, 'release': release,
        'acceptance_sha256': sha(args.acceptance), 'original_provider_sha256': ORIGINAL,
        'dependency_files': dependency_files,
        'status': 'STAGED ONLY; actual provider/preinit/installer guest acceptance required before final ZIP',
        'delivery': 'Baka preinit static exec, normal finit_module flags0; OEM disk files retained; boot_b transaction plus atomic metadata directory activation. No live replacement.'}, indent=2) + '\n')


if __name__ == '__main__':
    main()
