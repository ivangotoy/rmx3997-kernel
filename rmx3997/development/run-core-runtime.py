#!/usr/bin/python3
"""Run the exact production Image with its built-in UFS PCI driver in QEMU.

No test kernel config, real block device, phone or existing filesystem is used.
The driver is bound using Linux's standard PCI new_id interface in the guest.
"""
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
sys.dont_write_bytecode = True

repo = Path(__file__).resolve().parents[2]
cache = Path('/home/build/.cache/codex-work/rmx3997-feature-parity')
stage = cache / 'bakasu-susfs-stage1'
old = Path('/home/build/Downloads/rea-lk-analysis/rmx3997-custom-gki-build/oem-f2fs-implementation-20261103')
emergency = old.parent / 'ksu-next-susfs-integration-20261104/emergency-rollback-20261104'
normal = old / 'flashable-ak3-20261104/firmware-identity/normal-system-tools'
apk = Path('/home/build/Downloads/Telegram Desktop/BakaSU_v4.2.0-rc3_35252-arm64-v8a-release.apk')
def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()

env = os.environ.copy()
env.update(json.loads((stage / 'build-environment.json').read_text()))
image = stage / 'out/arch/arm64/boot/Image'
def execute(run):
    assert run.resolve().is_relative_to(cache.resolve())
    record = json.loads((run / 'inputs.json').read_text())
    assert not (run / 'console.log').exists(), 'Keep prior execution evidence'
    assert record['init_source_sha256'] == sha(repo / 'rmx3997/development/core-runtime.c')
    disk = Path(record['disk_path'])
    assert record['disk_before_sha256'] == sha(disk)
    assert json.loads((stage / 'build-execution.json').read_text())['exit_code'] == 0
    record['Image_sha256'] = sha(image)
    (run / 'inputs.json').write_text(json.dumps(record, indent=2) + '\n')
    with (run / 'console.log').open('wb') as f:
        try:
            p = subprocess.run(record['qemu_argv'], env=env, stdout=f,
                               stderr=subprocess.STDOUT, timeout=300)
            code = p.returncode
        except subprocess.TimeoutExpired:
            code = 124
    console = (run / 'console.log').read_text(errors='replace')
    skip = 'KernelSU may be already loaded in kernel, skip!' in console
    record.update(returncode=code, disk_after_sha256=sha(disk),
                  actual_patched_init_skipped_LKM=skip,
                  status='PASS' if code == 0 and 'CORE_RUNTIME_RESULT=PASS' in console and skip else 'FAIL',
                  checks=sorted(set(re.findall(r'^CORE_TEST .*$', console, re.M))))
    (run / 'results.json').write_text(json.dumps(record, indent=2) + '\n')
    print('Run:', run)
    print('\n'.join(record['checks']))
    print('CORE_RUNTIME', record['status'])
    sys.exit(0 if record['status'] == 'PASS' else 1)

if len(sys.argv) == 3 and sys.argv[1] == '--run-prepared':
    execute(Path(sys.argv[2]))
prepare_only = sys.argv[1:] == ['--prepare-only']
assert not sys.argv[1:] or prepare_only
if not prepare_only:
    assert json.loads((stage / 'build-execution.json').read_text())['exit_code'] == 0
assert sha(apk) == '43ccd6ec08844bf656b0800d84567c4f04412203446e6dada9570008f180fe25'
assert sha(emergency / 'bakasu-libksud.so') == 'e638066cafdf8e9146be9deb22a2b85e4d1d80343316585ffcc6a470e5f089d0'
run = cache / ('core-runtime-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'))
run.mkdir()
assert run.resolve().is_relative_to(cache.resolve())
(repo / 'rmx3997/development/latest-core-runtime.txt').write_text(str(run) + '\n')
include = run / 'include/linux'
include.mkdir(parents=True)
shutil.copy2(repo / 'include/uapi/linux/ntsync.h', include / 'ntsync.h')
tc = env['PATH'].split(':')[0]
ndk = old.parent / 'kernel/prebuilts/ndk-r23/toolchains/llvm/prebuilt/linux-x86_64/sysroot'
cc = [tc + '/clang', '--target=aarch64-linux-android31', '--sysroot=' + str(ndk),
      '-I' + str(run / 'include'), '-static', '-fuse-ld=lld', '--rtlib=compiler-rt',
      '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-sign-compare',
      str(repo / 'rmx3997/development/core-runtime.c'), '-o', str(run / 'init')]
with (run / 'compile.log').open('wb') as f:
    subprocess.run(cc, env=env, stdout=f, stderr=subprocess.STDOUT, check=True)
fixture = run / 'fixture'
app = fixture / 'app/~~fixture/org.bakasu.bakasu-fixture'
(app / 'lib/arm64').mkdir(parents=True)
(fixture / 'system').mkdir()
shutil.copy2(apk, app / 'base.apk')
shutil.copy2(emergency / 'bakasu-libksud.so', app / 'lib/arm64/libksud.so')
(app / 'lib/arm64/libksud.so').chmod(0o755)
(fixture / 'system/packages.list').write_text('org.bakasu.bakasu 10000 0 /data/user/0/org.bakasu.bakasu default none\n')
(fixture / 'FIXTURE_ID').write_text('RMX3997-CORE-DISPOSABLE-20261104\n')
disk = run / 'disposable-core.ext4'
with disk.open('xb') as f:
    f.truncate(536870912)
assert stat.S_ISREG(disk.lstat().st_mode) and not disk.is_symlink() and disk.stat().st_size == 536870912
mkfs = ['/usr/bin/mkfs.ext4', '-q', '-F', '-O', '^orphan_file', '-L', 'RMX3997CORE',
        '-d', str(fixture), str(disk)]
with (run / 'mkfs.log').open('wb') as f:
    subprocess.run(mkfs, env=env, stdout=f, stderr=subprocess.STDOUT, check=True)

# Reuse the retained archive producer, not a new packaging infrastructure.
spec = importlib.util.spec_from_file_location('retained_native', old / 'flashable-ak3-20261104/tests/android-integration/run.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
entries = {d: (stat.S_IFDIR | 0o755, b'', 0, 0) for d in ('dev', 'proc', 'sys', 'data', 'system', 'system/bin', 'system/lib64')}
entries['dev/console'] = (stat.S_IFCHR | 0o600, b'', 5, 1)
entries['dev/null'] = (stat.S_IFCHR | 0o666, b'', 1, 3)
module_check = old / 'flashable-ak3-20261104/module-check'
assert sha(module_check / 'init') == '682f7748906781c990401c6aa601f5d2c2806962d8f4ecb29e606d56131a4c35'
assert sha(module_check / 'kernelsu.ko') == '2d0f58a2829229a772e3ed69ea3ad1db79ae12dacc188f174868714c387bfc67'
entries['init'] = (stat.S_IFREG | 0o755, (module_check / 'init').read_bytes(), 0, 0)
entries['init.real'] = (stat.S_IFREG | 0o755, (run / 'init').read_bytes(), 0, 0)
entries['kernelsu.ko'] = (stat.S_IFREG | 0o644, (module_check / 'kernelsu.ko').read_bytes(), 0, 0)
entries['ksu_config'] = (stat.S_IFREG | 0o644, (module_check / 'ksu_config').read_bytes(), 0, 0)
busybox = old / 'flashable-ak3-20261104/candidate/contents/tools/busybox'
assert sha(busybox) == 'c629fce4b0dd3ba9775f851d0941e74582115f423258d3a79800f2bd11d30f5c'
entries['busybox'] = (stat.S_IFREG | 0o755, busybox.read_bytes(), 0, 0)
entries['system/bin/sh'] = (stat.S_IFLNK | 0o777, b'/busybox', 0, 0)
todo = [normal / 'linker64', normal / 'toybox', emergency / 'bakasu-libksud.so']
seen = set()
while todo:
    p = todo.pop()
    if p in seen:
        continue
    seen.add(p)
    dynamic = subprocess.check_output(['/usr/bin/readelf', '-d', str(p)], text=True)
    if p.name != 'bakasu-libksud.so':
        name = 'system/bin/' + p.name if p.name in ('linker64', 'toybox') else 'system/lib64/' + p.name
        entries[name] = (stat.S_IFREG | 0o755, p.read_bytes(), 0, 0)
    todo += [normal / 'linker64' if d == 'ld-android.so' else normal / 'lib64' / d
             for d in re.findall(r'Shared library: \[(.*?)\]', dynamic)]
native.archive(entries, run / 'initramfs.cpio.gz')
argv = ['/usr/bin/qemu-system-aarch64', '-machine', 'virt,gic-version=3,mte=on', '-cpu', 'max',
        '-accel', 'tcg,thread=multi', '-smp', '2', '-m', '2048M', '-nodefaults', '-no-user-config',
        '-display', 'none', '-monitor', 'none', '-serial', 'stdio', '-no-reboot', '-nic', 'none',
        '-kernel', str(image), '-initrd', str(run / 'initramfs.cpio.gz'),
        '-append', 'console=ttyAMA0 earlycon=pl011,0x09000000 rdinit=/init loglevel=7 panic=-1 nokaslr',
        '-device', 'ufs,id=rmxufs,serial=RMX3997-CORE-UFS,mcq=off',
        '-drive', 'file=' + str(disk) + ',if=none,format=raw,id=corefs',
        '-device', 'ufs-lu,drive=corefs,lun=0']
record = {'controller_build_argv': cc, 'mkfs_argv': mkfs, 'qemu_argv': argv,
          'init_source_sha256': sha(repo / 'rmx3997/development/core-runtime.c'),
          'init_sha256': sha(run / 'init'), 'initramfs_sha256': sha(run / 'initramfs.cpio.gz'),
          'disk_path': str(disk), 'disk_before_sha256': sha(disk), 'disk_bytes': disk.stat().st_size,
          'fixture_only': True, 'phone_operations': False, 'production_kernel_config_modified': False,
          'patched_init_wrapper_sha256': sha(module_check / 'init'),
          'LKM_present_but_must_not_load_sha256': sha(module_check / 'kernelsu.ko'),
          'status': 'PREPARED ONLY' if prepare_only else 'RUNNING'}
(run / 'inputs.json').write_text(json.dumps(record, indent=2) + '\n')
if prepare_only:
    print(run)
    sys.exit(0)
execute(run)
