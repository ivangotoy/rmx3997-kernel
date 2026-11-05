#!/usr/bin/env python3
"""Package an OEM-preserving Image using pinned WildKernels AnyKernel3.

No provider assets, preinit injection, modules, or metadata transaction enter
this delivery path. Historical provider tools and installer-repair evidence are
retained separately. Phone boot acceptance remains a separate operation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile

REPO = Path(__file__).resolve().parents[2]


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
    if not release.startswith('5.15.197-android13-8-'):
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


def package(image, output, identity):
    """Shared by production packaging and explicitly non-release guest fixtures."""
    core = REPO / 'rmx3997/development/wk-anykernel'
    if output.exists():
        raise FileExistsError(output)
    names = {'LICENSE', 'anykernel.sh', 'install-on-device.sh',
             'tools/ak3-core.sh', 'tools/busybox', 'tools/magiskboot',
             'tools/avbroot', 'tools/avbroot-LICENSE',
             'tools/avbroot-provenance.json', 'tools/rmx-avb.sh',
             'META-INF/com/google/android/update-binary',
             'META-INF/com/google/android/updater-script'}
    actual = {str(f.relative_to(core)) for f in core.rglob('*') if f.is_file()}
    if actual != names:
        raise ValueError('Unexpected AnyKernel package member')
    members = {name: (core / name).read_bytes() for name in names}
    avb = json.loads(members['tools/avbroot-provenance.json'])
    if (avb['binary_sha256'] != '8edf57de0b181a65a6915198972f539cb1d7d9f34825127e6bb81dd69cb323ed'
            or hashlib.sha256(members['tools/avbroot']).hexdigest() != avb['binary_sha256']
            or hashlib.sha256(members['tools/avbroot-LICENSE']).hexdigest() != avb['license_sha256']):
        raise ValueError('Pinned avbroot tool/license identity differs')
    origin = json.loads((core.parent / 'wk-anykernel-origin.json').read_text())
    for name, pin in origin['authenticated_binary_git_blobs'].items():
        data = members[name]
        if hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() != pin:
            raise ValueError('Pinned AnyKernel tool/license identity differs: ' + name)
    members['Image'] = image.read_bytes()
    members['manifest.json'] = (json.dumps({**identity,
        'AnyKernel3': 'WildKernels/AnyKernel3@0b46673ae91aee8d60bd6ee257b4d56d3f6a0114',
        'target': 'active boot only; existing ramdisk/DT/header retained',
        'phone_boot': 'UNVERIFIED', 'native_package_validation': 'PENDING',
        'boot_AVB_policy': 'CUSTOM-UNSIGNED AVB NONE; original NONE/SHA256_RSA2048 verified; requires 0/unlocked/orange; OEM signature removed; no vbmeta partition or rollback flag changes',
        'automatic_reboot': False}, indent=2) + '\n').encode()
    members['SHA256SUMS'] = ''.join(hashlib.sha256(data).hexdigest() + '  ' + name + '\n'
                                   for name, data in sorted(members.items())).encode()
    with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(members.items()):
            info = zipfile.ZipInfo(name, (2026, 11, 5, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            z.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
    output.with_suffix(output.suffix + '.sha256').write_text(sha(output) + '  ' + output.name + '\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage', type=Path, required=True)
    p.add_argument('--validation', type=Path, required=True,
                   help='Exact-byte build/ABI/OEM-layout validation record')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    identity = inspect(a.stage.resolve())
    validation = json.loads(a.validation.read_text())
    if any(validation.get(k) != v for k, v in identity.items()):
        raise ValueError('Validation belongs to different input bytes')
    checks = ('guarded_build', 'upstream_abi', 'oem_modules', 'persistent_f2fs_layout')
    if any(validation.get(k) != 'PASS' for k in checks):
        raise ValueError('Missing actual build/ABI/OEM-layout acceptance')
    identity['validation_sha256'] = sha(a.validation)
    package(a.stage.resolve() / 'out/arch/arm64/boot/Image', a.output, identity)
    print(json.dumps({'path': str(a.output), 'sha256': sha(a.output), **identity}, indent=2))


if __name__ == '__main__':
    main()
