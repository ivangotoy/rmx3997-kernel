#!/usr/bin/python3
"""Check the actual changed function against an independent integer reference."""
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import random
import subprocess

repo = Path(__file__).resolve().parents[2]
cache = Path('/home/build/.cache/codex-work/rmx3997-feature-parity/performance-fixtures')
source = repo / 'lib/math/int_sqrt.c'
text = source.read_text()
start = text.index('unsigned long int_sqrt(')
end = text.index('EXPORT_SYMBOL(int_sqrt);', start)
fixture = cache / 'sqrt-integrated-host.c'
fixture.write_text('#define BITS_PER_LONG 64\n' + text[start:end])
env = os.environ.copy()
env.update(TMPDIR=str(cache), PYTHONPYCACHEPREFIX=str(cache / 'pycache'), PYTHONDONTWRITEBYTECODE='1')
argv = ['/usr/bin/cc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror', str(fixture), '-o', str(cache / 'sqrt-integrated-host.so')]
subprocess.run(argv, env=env, check=True)
function = ctypes.CDLL(str(cache / 'sqrt-integrated-host.so')).int_sqrt
function.argtypes = [ctypes.c_ulong]
function.restype = ctypes.c_ulong
assert ctypes.sizeof(ctypes.c_ulong) == 8
rng = random.Random(0x3997)
cases = set(range(256)) | {2**64 - 1}
for bit in range(64):
    for delta in (-1, 0, 1):
        value = (1 << bit) + delta
        if 0 <= value < 2**64:
            cases.add(value)
for _ in range(500000):
    cases.add(rng.getrandbits(64))
errors = []
for value in sorted(cases):
    actual, expected = function(value), math.isqrt(value)
    if actual != expected:
        errors.append({'input': value, 'actual': actual, 'expected': expected})
record = {'source_commit_before_change': subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip(),
          'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
          'donor': 'ee68218dc83b3e488ae619eb82e868859e8eb17d:common/int_sqrt.patch',
          'adaptation': 'Do not unconditionally discard the 1UL<<62 candidate; retain public function signature and normal kernel style.',
          'scope': 'Actual integrated function extracted into a host arithmetic fixture, not kernel runtime or performance certification',
          'argv': argv, 'seed': 0x3997, 'cases': len(cases), 'errors': errors,
          'status': 'PASS' if not errors else 'FAIL'}
(repo / 'rmx3997/development/int-sqrt-integrated-tests.json').write_text(json.dumps(record, indent=2) + '\n')
print(record['status'], record['cases'])
raise SystemExit(bool(errors))
