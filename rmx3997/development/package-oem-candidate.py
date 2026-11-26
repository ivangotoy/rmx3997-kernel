#!/usr/bin/env python3
"""Inspect an OEM-preserving Image and package it with stock WildKernels
AnyKernel3 at its upstreams.json pin, unmodified, as the GKI kernels do.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile

REPO = Path(__file__).resolve().parents[2]
GIT_ENV = dict(os.environ, GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1',
               GIT_TERMINAL_PROMPT='0', LC_ALL='C')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inspect(stage):
    out = stage / 'out'
    config = (out / '.config').read_text()
    symbols = (out / 'System.map').read_text()
    if 'CONFIG_CRYPTO_ZRAM_MULTI=y' in config or re.search(r'\bzram_multi_\w+', symbols):
        raise ValueError('Incompatible replacement-codec Image; rebuild required')
    if '__ksymtab_cgroup_rm_cftypes' in symbols:
        raise ValueError('Retired provider-only export remains in Image')
    required = ['CONFIG_KSU=y', 'CONFIG_KSU_SUSFS=y', 'CONFIG_MODVERSIONS=y',
                'CONFIG_MODULE_SIG_PROTECT=y', 'CONFIG_TRIM_UNUSED_KSYMS=y',
                'CONFIG_CFI_CLANG=y', 'CONFIG_LTO_CLANG_FULL=y', 'CONFIG_ZRAM=m']
    if not all(line in config.splitlines() for line in required):
        raise ValueError('Root/OEM ABI/protection configuration differs')
    release = (out / 'include/config/kernel.release').read_text().strip()
    if not re.match(r'5\.15\.\d+-android13-8-', release):
        raise ValueError('Wrong base/KMI family')
    image = out / 'arch/arm64/boot/Image'
    embedded = subprocess.check_output([str(REPO / 'scripts/extract-ikconfig'), str(image)])
    if embedded != config.encode():
        raise ValueError('Image embedded config differs from effective config')
    data = image.read_bytes()
    if data[56:60] != b'ARM\x64':
        raise ValueError('Not a raw ARM64 Image')
    return {'Image_sha256': sha(image), 'vmlinux_sha256': sha(out / 'vmlinux'),
            'config_sha256': sha(out / '.config'), 'release': release}


def package(image, output, identity, ak3, url, pin):
    """The release ZIP: stock AnyKernel3 at its pin, unmodified, plus Image and a
    provenance record, the same way the GKI kernels are packaged."""
    if output.exists():
        raise FileExistsError(output)
    git = lambda *args, text=True: subprocess.run(
        ['git', '-C', str(ak3), *args], capture_output=True, check=True, text=text,
        env=dict(GIT_ENV)).stdout
    if git('rev-parse', 'HEAD').strip() != pin:
        raise ValueError('AnyKernel3 checkout is not the pinned commit')
    if git('status', '--porcelain', '--ignored', '--untracked-files=all').strip():
        raise ValueError('AnyKernel3 checkout differs from the pinned commit')
    members = {}
    for entry in git('ls-tree', '-r', '-z', 'HEAD').split('\0'):
        if not entry:
            continue
        meta, name = entry.split('\t', 1)
        mode, kind, blob = meta.split()
        if name.startswith('.github/'):
            continue
        if kind != 'blob' or mode not in ('100644', '100755'):
            raise ValueError('AnyKernel3 member is not a regular file: ' + name)
        members[name] = git('cat-file', 'blob', blob, text=False)
    for name in REQUIRED:
        if name not in members:
            raise ValueError('AnyKernel3 member missing: ' + name)
    if any('Image' in Path(n).name for n in members):
        raise ValueError('AnyKernel3 tree already carries an Image')
    members['Image'] = image.read_bytes()
    members['rmx3997-provenance.json'] = (json.dumps(
        {**identity, 'AnyKernel3': {'url': url, 'commit': pin}}, indent=2) + '\n').encode()
    with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data in sorted(members.items(), key=lambda x: x[0].encode()):
            info = zipfile.ZipInfo(name, (2026, 11, 5, 0, 0, 0))
            info.external_attr = mode_of(name) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    check_zip(output)
    output.with_suffix(output.suffix + '.sha256').write_text(sha(output) + '  ' + output.name + '\n')


REQUIRED = ('anykernel.sh', 'tools/ak3-core.sh', 'META-INF/com/google/android/update-binary')


def mode_of(name):
    executable = (name in ('anykernel.sh', 'META-INF/com/google/android/update-binary')
                  or name.startswith('tools/'))
    return 0o100755 if executable else 0o100644


def check_zip(path):
    """Member contract of the GKI packages: no duplicates, exactly one Image,
    no patch residue, safe regular-file paths, deflate, canonical modes."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if len(names) != len(set(names)):
            raise ValueError('duplicate ZIP entries')
        if z.testzip() is not None:
            raise ValueError('corrupt ZIP member')
        if [n for n in names if 'Image' in Path(n).name] != ['Image']:
            raise ValueError('ZIP payload is not exactly one Image')
        for info in z.infolist():
            p = Path(info.filename)
            if p.is_absolute() or '..' in p.parts or p.suffix == '.patch':
                raise ValueError('unsafe or patch ZIP member: ' + info.filename)
            if info.compress_type != zipfile.ZIP_DEFLATED:
                raise ValueError('unexpected compression: ' + info.filename)
            if info.external_attr >> 16 != mode_of(info.filename):
                raise ValueError('non-canonical mode: ' + info.filename)
