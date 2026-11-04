#!/usr/bin/python3
"""Run the pinned fork's actual binary inventory reader without claiming FULL."""
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
source = repo / '.cache/parity-sources/aimax-fork'
commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
assert commit == '51d8178a3cde8f529ef71c5592f05b9ae513f96a'
blob = subprocess.check_output(['git', '-C', str(source), 'show',
                                commit + ':tools/compiled-config-inventory.py'])
assert blob == (source / 'tools/compiled-config-inventory.py').read_bytes()
assert os.environ.get('TMPDIR', '').startswith('/home/build/.cache/codex-work/')
sys.path.insert(0, str(source / 'tools'))
spec = importlib.util.spec_from_file_location('fork_inventory', source / 'tools/compiled-config-inventory.py')
fork = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fork)
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
image = a.stage / 'out/arch/arm64/boot/Image'
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
          'note': 'Original fork reader/functions and FULL symbol list run unchanged. No calibration bypass or replacement of missing features by config claims.'}
a.output.write_text(json.dumps(record, indent=2) + '\n')
print(record['status']); print('Missing FULL flags:', missing)
