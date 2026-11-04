#!/usr/bin/python3
"""Package only the validated boot payload and the proven installer closure."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

repo = Path(__file__).resolve().parents[2]
root = Path('/home/build/.cache/codex-work/rmx3997-feature-parity/bakasu-susfs-stage1')
p = root / 'flashable-ak3-core'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
tests = json.loads(Path((p / 'tests/latest-results-path.txt').read_text().strip()).read_text())
assert tests['overall'] == 'PASS' and len(tests['results']) == 25
assert tests['core_sha256'] == sha(p / 'installer-core.sh')
delivery = repo / 'rmx3997/development/delivery-core'
validation = json.loads((delivery / 'validation.json').read_text())
payload = delivery / 'boot_b_bakasu_susfs_core.img'
assert sha(payload) == validation['boot_sha256']
assert payload.stat().st_size == 67108864
candidate = p / 'candidate'
candidate.mkdir()
contents = candidate / 'contents'
contents.mkdir()
for name in ('anykernel.sh', 'installer-core.sh', 'android-platform.sh', 'install-on-device.sh', 'LICENSE'):
    shutil.copy2(p / name, contents / name)
meta = contents / 'META-INF/com/google/android'
meta.mkdir(parents=True)
shutil.copy2(p / 'update-binary', meta / 'update-binary')
ak = Path('/home/build/Downloads/rea-lk-analysis/wildkernels-investigation/zip')
shutil.copy2(ak / 'META-INF/com/google/android/updater-script', meta / 'updater-script')
(contents / 'tools').mkdir()
shutil.copy2(ak / 'tools/busybox', contents / 'tools/busybox')
assert sha(contents / 'tools/busybox') == 'c629fce4b0dd3ba9775f851d0941e74582115f423258d3a79800f2bd11d30f5c'
shutil.copy2(payload, contents / 'boot.img')
manifest = dict(validation)
manifest.update(target='boot_b only', current_working_boot_sha256='64da6e27c094fd43afe33a345fd53b023f5201c1150d2a1b1e8ff0428cf48881',
                init_boot='Read only; exact verified BakaSU-patched 22f6caff...deee9 remains unchanged',
                root='Built-in BakaSU only; actual retained init wrapper skipped its LKM in the guest',
                AVB='Fresh SHA256 descriptor/footer, algorithm NONE, no OEM signature trust claim',
                installer_core_sha256=tests['core_sha256'], core_transaction_cases=25,
                native_installation='PENDING BEFORE DELIVERY', write_path_enabled=True,
                automatic_reboot=False)
(contents / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
(contents / 'README.txt').write_text('''RMX3997 BakaSU + SUSFS CORE CHECKPOINT, experimental, Android16 EX01 slot B.
This is not the completed WildKernels/fork feature-parity target.

Boot-only installer: complete 64MiB backup/write/readback/verified rollback.
Requires the verified current working boot64da and patched init_boot22f6.
Keeps init_boot, BakaSU userspace, userdata, metadata and all other partitions.
The actual init wrapper detected the built-in driver and skipped loading the LKM
in a production-binary ARM64 guest. No root migration is performed.

Kernel build, upstream ABI, all463 OEM-module checks, persistent F2FS layouts
and20 core guest checks passed. The image was independently unpacked/decompressed
and AVB-checked. This image/package has not been executed on the phone.
Android boot/FBE/hardware crypto, encryption/crash recovery and independent slot
fallback are not certified. A backup cannot restore itself after an unbootable
kernel. Keep the separately verified external emergency recovery available;
do not assume slot A or automatic A/B fallback is usable.

No automatic reboot. Installer exit0 means verified installation; exit70 means
installation failed and the original boot was restored and verified. Exit71 means
recovery was not verified: DO NOT REBOOT. Keep the private transaction files.
''')
members = sorted(f for f in contents.rglob('*') if f.is_file())
(contents / 'SHA256SUMS').write_text(''.join(sha(f) + '  ' + str(f.relative_to(contents)) + '\n' for f in members))
zpath = candidate / 'RMX3997-BakaSU-SUSFS-CORE-5.15.197-EXPERIMENTAL-AK3.zip'
with zipfile.ZipFile(zpath, 'x', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for f in sorted(f for f in contents.rglob('*') if f.is_file()):
        name = str(f.relative_to(contents))
        info = zipfile.ZipInfo(name, date_time=(2026, 11, 4, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = (0o100755 if f.suffix == '.sh' or f.name in ('busybox', 'update-binary') else 0o100644) << 16
        z.writestr(info, f.read_bytes())
with zipfile.ZipFile(zpath) as z:
    assert z.testzip() is None and len(z.namelist()) == 12
    assert hashlib.sha256(z.read('boot.img')).hexdigest() == validation['boot_sha256']
    assert not any('init_boot' in name or name.endswith('.ko') or name.startswith('tests/') for name in z.namelist())
(candidate / 'package-identity.json').write_text(json.dumps({'path': str(zpath), 'sha256': sha(zpath),
    'bytes': zpath.stat().st_size, 'files': 12, 'native_acceptance': 'PENDING'}, indent=2) + '\n')
print(zpath)
