#!/usr/bin/python3
"""Bind the proven boot-only installer/tests to this validated core payload."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
sys.dont_write_bytecode = True

repo = Path(__file__).resolve().parents[2]
stage = Path('/home/build/.cache/codex-work/rmx3997-feature-parity/bakasu-susfs-stage1')
old = Path('/home/build/Downloads/rea-lk-analysis/rmx3997-custom-gki-build/oem-f2fs-implementation-20261103')
previous = old / 'flashable-ak3-20261104'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
working = Path('/home/build/Downloads/RMX3997_custom_boot_b_WORKING.img')
assert sha(working) == '64da6e27c094fd43afe33a345fd53b023f5201c1150d2a1b1e8ff0428cf48881'
payload = stage / 'experimental-anykernel3-20261104/boot_b_oem_f2fs_experimental.img'
validation = json.loads((repo / 'rmx3997/development/delivery-core/validation.json').read_text())
assert sha(payload) == validation['boot_sha256']
p = stage / 'flashable-ak3-core'
p.mkdir(exist_ok=False)
for name in ('installer-core.sh', 'android-platform.sh', 'anykernel.sh', 'update-binary', 'install-on-device.sh', 'LICENSE'):
    shutil.copy2(repo / 'rmx3997/installer' / name, p / name)
core = p / 'installer-core.sh'
s = core.read_text().replace('EXPECTED_PAYLOAD=64da6e27c094fd43afe33a345fd53b023f5201c1150d2a1b1e8ff0428cf48881',
                             'EXPECTED_PAYLOAD=' + sha(payload))
s = s.replace('EXPECTED_STOCK=c7ab487bac1e2fb99932738aa423d5553b4ad8bcd2b8fc4677b8c491981fe086',
              'EXPECTED_STOCK=' + sha(working))
s = s.replace('boot is not known-good stock baseline', 'boot is not the verified working RMX3997 baseline')
core.write_text(s)
(p / 'tests').mkdir()
for name in ('run-installer-tests.py', 'fixture_support.py', 'platform-simulation.sh', 'test-driver.sh'):
    shutil.copy2(previous / 'tests' / name, p / 'tests' / name)
t = p / 'tests/run-installer-tests.py'
s = t.read_text().replace('/home/build/Downloads/RMX3997_16.0.5.1300_boot_b_stock.img', str(working))
s = s.replace('c7ab487bac1e2fb99932738aa423d5553b4ad8bcd2b8fc4677b8c491981fe086', sha(working))
# Replace the payload pin only after substituting the baseline pin.
s = s.replace("PAYLOAD:'64da6e27c094fd43afe33a345fd53b023f5201c1150d2a1b1e8ff0428cf48881'", "PAYLOAD:'" + sha(payload) + "'")
t.write_text(s)
native = p / 'tests/android-integration'
native.mkdir()
for name in ('run.py', 'init.c', 'init'):
    shutil.copy2(previous / 'tests/android-integration' / name, native / name)
t = native / 'run.py'
s = t.read_text().replace('/home/build/Downloads/RMX3997_16.0.5.1300_boot_b_stock.img', str(working))
s = s.replace("EXPECTED_STOCK='c7ab487bac1e2fb99932738aa423d5553b4ad8bcd2b8fc4677b8c491981fe086'", "EXPECTED_STOCK='" + sha(working) + "'")
s = s.replace("EXPECTED_PAYLOAD='64da6e27c094fd43afe33a345fd53b023f5201c1150d2a1b1e8ff0428cf48881'", "EXPECTED_PAYLOAD='" + sha(payload) + "'")
t.write_text(s)
(p / 'firmware-identity').mkdir()
(p / 'firmware-identity/normal-system-tools').symlink_to(previous / 'firmware-identity/normal-system-tools')
(stage / 'qemu-guest-boot-20261103').symlink_to(old / 'qemu-guest-boot-20261103')
record = {'core_sha256': sha(core), 'boot_payload_sha256': sha(payload),
          'current_working_boot_sha256': sha(working), 'init_boot': 'unchanged, pinned 22f6caff...deee9',
          'changes': ['payload hash', 'verified current working baseline hash', 'matching baseline rejection text'],
          'all_other_installer_checks': 'retained', 'native_controller_rebuilt': False,
          'phone_operations': False}
(p / 'preparation.json').write_text(json.dumps(record, indent=2) + '\n')
print(p)
