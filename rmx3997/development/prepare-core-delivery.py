#!/usr/bin/python3
"""Assemble the validated core checkpoint using the retained boot procedure."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
sys.dont_write_bytecode = True

repo = Path(__file__).resolve().parents[2]
stage = Path('/home/build/.cache/codex-work/rmx3997-feature-parity/bakasu-susfs-stage1')
old = Path('/home/build/Downloads/rea-lk-analysis/rmx3997-custom-gki-build/oem-f2fs-implementation-20261103')
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
env = os.environ.copy()
env.update(json.loads((stage / 'build-environment.json').read_text()))
assert json.loads((stage / 'build-execution.json').read_text())['exit_code'] == 0
assert all(json.loads((stage / 'abi/binary-check-acceptance.json').read_text()).values())
assert all(x['exit_code'] == 0 for x in json.loads((stage / 'abi/upstream-check-execution.json').read_text()))
runtime = Path((repo / 'rmx3997/development/latest-core-runtime.txt').read_text().strip())
rt = json.loads((runtime / 'results.json').read_text())
image = stage / 'out/arch/arm64/boot/Image'
assert rt['status'] == 'PASS' and rt['actual_patched_init_skipped_LKM']
assert rt['Image_sha256'] == sha(image)
assert len(rt['checks']) == 20 and all('=PASS' in s for s in rt['checks'])
# No changed kernel producer may be mislabeled with the validated binary.
changed = subprocess.check_output(['git', 'diff', '--name-only', '8e409222a'], cwd=repo, text=True).splitlines()
assert all(p.startswith('rmx3997/development/') for p in changed), changed
delivery = repo / 'rmx3997/development/delivery-core'
delivery.mkdir(exist_ok=False)
boot = stage / 'experimental-anykernel3-20261104'
boot.mkdir(exist_ok=False)
for name in ('assemble_boot.py', 'verify_boot.py'):
    s = (old / 'experimental-anykernel3-20261104' / name).read_text()
    s = s.replace('46ed4afd78b624cb67acc8524bd285f6cd506a9131a40a262c3dd202ec3ddcfd', sha(image))
    (boot / name).write_text(s)
comp = boot / 'kernel.legacy-lz4'
with comp.open('xb') as f:
    subprocess.run(['/home/linuxbrew/.linuxbrew/bin/lz4', '-l', '-9', '-c', str(image)],
                   env=env, stdout=f, stderr=subprocess.PIPE, check=True)
p = boot / 'assemble_boot.py'
p.write_text(p.read_text().replace('6efb2a5aa2e50116d4979e96216c28d48e4ed4de5991ee786c29269599826452', sha(comp)))
for name in ('assemble_boot.py', 'verify_boot.py'):
    with (boot / (name + '.log')).open('wb') as f:
        subprocess.run(['/usr/bin/python3', str(boot / name)], env=env, stdout=f,
                       stderr=subprocess.STDOUT, check=True)
payload = boot / 'boot_b_oem_f2fs_experimental.img'
verified = json.loads((boot / 'independent-validation.json').read_text())['results'][payload.name]
assert verified['sha256'] == sha(payload) and verified['decoded_kernel_sha256'] == sha(image)
assert verified['native_avb_verification_pass'] and verified['independent_unpack_pass']
assert verified['partition_bytes'] == 67108864 and verified['algorithm_type'] == verified['authentication_bytes'] == 0
shutil.copy2(image, delivery / 'Image')
shutil.copy2(payload, delivery / 'boot_b_bakasu_susfs_core.img')
shutil.copy2(stage / 'out/.config', delivery / 'production.config')
for name in ('assembly-record.json', 'independent-validation.json'):
    shutil.copy2(boot / name, delivery / name)
record = {'kernel_code_commit': subprocess.check_output(['git', 'rev-parse', '8e409222a'], cwd=repo, text=True).strip(),
          'Image_sha256': sha(image), 'boot_sha256': sha(payload),
          'release': (stage / 'out/include/config/kernel.release').read_text().strip(),
          'upstream_ABI': 'PASS', 'OEM_unique_modules': 463, 'module_checks': 'PASS',
          'persistent_F2FS_layouts': 'PASS', 'production_guest_checks': rt['checks'],
          'actual_patched_init_skipped_LKM': True, 'runtime_record': str(runtime / 'results.json'),
          'full_feature_parity': False, 'phone_tested': False,
          'pending': ['BBRv3 ABI-safe implementation', 'remaining performance patches',
                      'ZRAM multi-compression with OEM provider', 'upstream 5.15 development stage',
                      'remaining recipe-specific features and engineering contracts',
                      'Android encryption/crash recovery/device boot']}
(delivery / 'validation.json').write_text(json.dumps(record, indent=2) + '\n')
(delivery / 'SHA256SUMS').write_text(''.join(sha(p) + '  ' + p.name + '\n'
                                         for p in sorted(delivery.iterdir()) if p.is_file()))
print(json.dumps({'delivery': str(delivery), 'Image': sha(image), 'boot': sha(payload)}, indent=2))
