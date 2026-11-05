#!/usr/bin/python3
"""Read a new candidate using the primary pinned reader; no runtime FULL claim."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
sys.dont_write_bytecode = True

repo = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('stage', type=Path)
parser.add_argument('output', type=Path)
a = parser.parse_args()
source = Path('/home/build/Downloads/GKI_KernelSU_SUSFS')
commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
assert commit == 'bcc9c39fa0d58027739dae3cb07baa6e01c98db9'
blob = subprocess.check_output(['git', '-C', str(source), 'show',
                                commit + ':tools/compiled-config-inventory.py'])
assert blob == (source / 'tools/compiled-config-inventory.py').read_bytes()
assert os.environ.get('TMPDIR', '').startswith('/home/build/.cache/codex-work/')
sys.path.insert(0, str(source / 'tools'))
spec = importlib.util.spec_from_file_location('fork_inventory', source / 'tools/compiled-config-inventory.py')
fork = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fork)
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
build = json.loads((a.stage / 'build-execution.json').read_text())
assert build['exit_code'] == 0 and build['reason'] == 'completed'
assert build['argv'] == json.loads((a.stage / 'build-argv.json').read_text())
assert build['memory_floor_bytes'] >= 8*1024**3 and build['log_limit_bytes'] <= 64*1024**2
assert build['test_only_injected_pressure'] is False
image = a.stage / 'out/arch/arm64/boot/Image'
assert sha(image) != 'e2e7bdd324419318b5da8571817da9c1ffcfa925b821c78c277b287c6209fefa', 'Inherited core Image is not a new candidate'

embedded = fork.extract_ikconfig(image)
config = (a.stage / 'out/.config').read_bytes()
assert embedded == config, 'Embedded binary config differs from build config'
values = fork.parse_symbols(embedded.decode())
release = (a.stage / 'out/include/config/kernel.release').read_text().strip()
banner = fork.extract_banner(image, release)
compiler = fork.parse_compiler_identity(banner)
assert compiler['clang_version'].startswith('14.')
missing = {symbol: values.get(symbol, 'absent') for symbol in fork.WILD_FULL_BUILTIN_SYMBOLS
           if values.get(symbol) != 'y'}
required = ['CONFIG_CFI_CLANG', 'CONFIG_MODVERSIONS', 'CONFIG_MODULE_SIG_PROTECT',
            'CONFIG_LTO_CLANG_FULL', 'CONFIG_F2FS_FS_DEDUP',
            'CONFIG_F2FS_FS_COMPRESSION_FIXED_OUTPUT', 'CONFIG_KSU', 'CONFIG_KSU_SUSFS']
assert all(values.get(symbol) == 'y' for symbol in required)
record = {'donor_commit': commit, 'reader_path': 'tools/compiled-config-inventory.py',
          'reader_sha256': sha(source / 'tools/compiled-config-inventory.py'),
          'stage': str(a.stage), 'Image_sha256': sha(image),
          'embedded_config_equals_build_config': True,
          'embedded_config_sha256': hashlib.sha256(embedded).hexdigest(),
          'compiler': compiler, 'feature_audit': fork.build_feature_audit(values),
          'selected_symbols': {s: values.get(s, 'absent') for s in fork.SELECTED_SYMBOLS},
          'wild_full_missing_builtin': missing,
          'full_parity': False, 'status': 'BINARY INVENTORY PASS; FULL PROFILE HAS GAPS' if missing else 'BINARY INVENTORY PASS; semantic/runtime parity still separately required',
          'root_source_identity': json.loads((repo / 'rmx3997/development/root-sources.json').read_text())['BakaSU'],
          'note': 'Original primary reader/functions and FULL symbol list run unchanged. Config coverage does not prove runtime or OEM recompress ABI; no calibration bypass or config substitution.'}
with a.output.open('x') as f:
    json.dump(record,f,indent=2);f.write('\n')
print(record['status']); print('Missing FULL flags:', missing)
