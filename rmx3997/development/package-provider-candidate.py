#!/usr/bin/python3
"""Create a local draft ZIP from actual new Image-bound boot/provider assets.

Parent must validate this exact draft in the production-Image guest/native
installer before delivery. This never installs, publishes or claims phone boot.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import zipfile

REPO = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def provider_core_script(script):
    """Coordinate signal ownership without modifying the retained core."""
    # Bind the complete retained transaction, including terminal success/no-op.
    # EXPECTED_PAYLOAD is rebound by the packager, so normalize only that field.
    template = re.sub(r'(?m)^EXPECTED_PAYLOAD=[0-9a-f]{64}$',
                      'EXPECTED_PAYLOAD=<bound-payload>', script)
    if hashlib.sha256(template.encode()).hexdigest() != '33fdce702433deae7bb815c9c38c7153a02ea959efbf475595b0c2e7c1bb27ff':
        raise ValueError('Unknown complete core transaction template')
    changes = [
        ('''installer_unlock() {
    trap - INT TERM HUP
    platform_unlock "$WORKDIR" || installer_log 'Lock cleanup failed; retain logs and remove no files automatically.'
}
''', '''installer_unlock() {
    trap '' INT TERM HUP
    local unlock_result=0
    platform_unlock "$WORKDIR" || {
        installer_log 'Lock cleanup failed; retain logs and remove no files automatically.'
        INSTALLER_CLEANUP_FAILED=1
        unlock_result=71
    }
    INSTALLER_LOCK_HELD=0
    if [ "${INSTALLER_INTERRUPTED:-0}" != 1 ]; then
        if [ "${PROVIDER_TRANSACTION_ACTIVE:-0}" = 1 ]; then
            trap provider_interrupt INT TERM HUP
        else
            trap - INT TERM HUP
        fi
    fi
    return "$unlock_result"
}
'''),
        ('installer_restore() {\n', "installer_restore() {\n    trap '' INT TERM HUP\n    INSTALLER_RESTORE_STARTED=1\n    INSTALLER_RESULT=71\n"),
        ('installer_interrupt() {\n', 'installer_interrupt() {\n    trap \'\' INT TERM HUP\n    INSTALLER_INTERRUPTED=1\n    if [ "${PROVIDER_COMMITTED:-0}" = 1 ]; then provider_interrupt 0; fi\n'),
        ('    installer_unlock\n    exit "$code"\n', '''    installer_unlock
    if [ "${PROVIDER_TRANSACTION_ACTIVE:-0}" = 1 ]; then
        provider_interrupt "$code"
    fi
    exit "$code"
'''),
        ('    platform_lock "$WORKDIR" || { installer_reject \'another installation holds the lock\'; return 10; }\n    trap installer_interrupt INT TERM HUP\n', '''    INSTALLER_PENDING_SIGNAL=0
    trap 'INSTALLER_PENDING_SIGNAL=1' INT TERM HUP
    if ! platform_lock "$WORKDIR"; then
        if [ "${PROVIDER_TRANSACTION_ACTIVE:-0}" = 1 ]; then
            trap provider_interrupt INT TERM HUP
        else
            trap - INT TERM HUP
        fi
        installer_reject 'another installation holds the lock'
        return 10
    fi
    INSTALLER_LOCK_HELD=1
    trap installer_interrupt INT TERM HUP
    [ "$INSTALLER_PENDING_SIGNAL" = 0 ] || installer_interrupt
'''),
        ('    WRITE_STARTED=0\n    installer_log "ROLLBACK VERIFIED:', '    WRITE_STARTED=0\n    INSTALLER_RESULT=70\n    installer_log "ROLLBACK VERIFIED:'),
        ('    WRITE_STARTED=0\n    installer_log "INSTALL VERIFIED:', '    provider_commit || installer_interrupt\n    installer_log "INSTALL VERIFIED:'),
        ("        installer_log 'NO-OP: exact candidate already present; no partition writes'", "        provider_commit || installer_interrupt\n        installer_log 'NO-OP: exact candidate already present; no partition writes'"),
    ]
    for old, new in changes:
        if script.count(old) != 1:
            raise ValueError('Unknown core signal template: ' + old.splitlines()[0])
        script = script.replace(old, new, 1)
    return script


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', type=Path, required=True)
    parser.add_argument('--boot', type=Path, required=True)
    parser.add_argument('--provider-assets', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    image = args.stage / 'out/arch/arm64/boot/Image'
    vmlinux = args.stage / 'out/vmlinux'
    assets = args.provider_assets.resolve()
    provider = json.loads((assets / 'manifest.json').read_text())
    if provider['Image_sha256'] != sha(image) or provider['vmlinux_sha256'] != sha(vmlinux):
        raise ValueError('Provider assets differ from the actual new Image')
    if sha(image) == 'e2e7bdd324419318b5da8571817da9c1ffcfa925b821c78c277b287c6209fefa':
        raise ValueError('Inherited core Image is not this candidate')
    boot = args.boot.read_bytes()
    if len(boot) != 67108864 or boot[:8] != b'ANDROID!':
        raise ValueError('Expected actual64MiB Android boot payload')
    kernel_size = struct.unpack_from('<I', boot, 8)[0]
    header_size = struct.unpack_from('<I', boot, 20)[0]
    version = struct.unpack_from('<I', boot, 40)[0]
    if version not in (3, 4) or header_size > 4096 or not kernel_size:
        raise ValueError('Unexpected boot header')
    kernel = boot[4096:4096 + kernel_size]
    if kernel[:2] == b'\x1f\x8b': kernel = gzip.decompress(kernel)
    elif kernel[:4] == bytes.fromhex('02214c18'):
        decoder = Path('/home/build/Downloads/rea-lk-analysis/rmx3997-custom-gki-build/kernel/prebuilts/kernel-build-tools/linux-x86/bin/lz4')
        kernel = subprocess.run([str(decoder), '-d', '-c'], input=kernel,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                check=True).stdout
    if hashlib.sha256(kernel).hexdigest() != sha(image):
        raise ValueError('Boot contains a different kernel')
    output = args.output.resolve()
    if output.exists(): raise ValueError('Refuse to overwrite artifact')
    contents = output.parent / (output.name + '.contents')
    contents.mkdir(parents=True, exist_ok=False)
    (contents / 'provider').mkdir()
    names = ['provider-loader', 'provider.ko', 'original-provider.ko', 'preinit.conf',
             'provider-release.sh', 'provider-install-entry.sh', 'provider-transaction.sh',
             'provider-android.sh', 'manifest.json']
    if len(provider['dependency_files']) != 7:
        raise ValueError('Missing exact dependency closure')
    names += ['provider-dependencies.sha256'] + sorted(provider['dependency_files'])
    for name in names: shutil.copy2(assets / name, contents / 'provider' / name)
    for field, name in [('PROVIDER_MODULE_SHA256', 'provider.ko'),
                        ('PROVIDER_LOADER_SHA256', 'provider-loader'),
                        ('PROVIDER_CONF_SHA256', 'preinit.conf')]:
        if provider['release'][field] != sha(contents / 'provider' / name):
            raise ValueError('Provider asset changed: ' + name)
    if sha(contents / 'provider/original-provider.ko') != provider['original_provider_sha256']:
        raise ValueError('Rollback provider changed')
    if sha(contents / 'provider/provider-dependencies.sha256') != provider['release']['PROVIDER_DEPS_SHA256']:
        raise ValueError('Dependency manifest changed')
    for name, digest in provider['dependency_files'].items():
        if sha(contents / 'provider' / name) != digest:
            raise ValueError('Dependency changed: ' + name)
    core = REPO / 'rmx3997/development/installer-core-checkpoint'
    for name in ('installer-core.sh', 'android-platform.sh', 'LICENSE'):
        shutil.copy2(core / name, contents / name)
    script = (contents / 'installer-core.sh').read_text()
    script, count = re.subn(r'(?m)^EXPECTED_PAYLOAD=[0-9a-f]{64}$',
                            'EXPECTED_PAYLOAD=' + sha(args.boot), script)
    if count != 1: raise ValueError('Unknown core transaction template')
    (contents / 'installer-core.sh').write_text(provider_core_script(script))
    installer = REPO / 'rmx3997/provider/installer'
    for name in ('anykernel.sh', 'install-on-device.sh'):
        shutil.copy2(installer / name, contents / name)
    meta = contents / 'META-INF/com/google/android'
    meta.mkdir(parents=True)
    shutil.copy2(installer / 'update-binary', meta / 'update-binary')
    upstream = Path('/home/build/Downloads/rea-lk-analysis/wildkernels-investigation/zip')
    shutil.copy2(upstream / 'META-INF/com/google/android/updater-script', meta / 'updater-script')
    (contents / 'tools').mkdir()
    busybox = upstream / 'tools/busybox'
    if sha(busybox) != 'c629fce4b0dd3ba9775f851d0941e74582115f423258d3a79800f2bd11d30f5c':
        raise ValueError('Bootstrap differs')
    shutil.copy2(busybox, contents / 'tools/busybox')
    shutil.copy2(args.boot, contents / 'boot.img')
    manifest = {'status': 'DRAFT; exact package/native rollback/guest validation required before delivery',
                'boot_sha256': sha(args.boot), 'Image_sha256': sha(image),
                'provider': provider, 'init_boot': 'unchanged', 'vendor_dlkm': 'original bytes unchanged',
                'rollback': 'Existing boot backup/readback restoration plus atomic preinit directory deactivation',
                'phone_boot': 'UNTESTED', 'automatic_reboot': False}
    (contents / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (contents / 'README.txt').write_text('RMX3997 ACK5.15.197 BakaSU/SUSFS/provider candidate.\n'
        'DRAFT: no delivery/phone boot acceptance. Keeps original OEM provider and init_boot.\n'
        'Provider preinit loads only with matching new kernel notes and module hashes.\n'
        'Normal kernel loader checks remain enabled. No live swap replacement.\n'
        'Installer verifies boot backup/write/readback and metadata rollback. No automatic reboot.\n')
    files = sorted(path for path in contents.rglob('*') if path.is_file())
    (contents / 'SHA256SUMS').write_text(''.join(sha(path) + '  ' + str(path.relative_to(contents)) + '\n' for path in files))
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(p for p in contents.rglob('*') if p.is_file()):
            info = zipfile.ZipInfo(str(path.relative_to(contents)), (2026, 11, 4, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
    output.with_suffix(output.suffix + '.sha256').write_text(sha(output) + '  ' + output.name + '\n')


if __name__ == '__main__':
    main()
