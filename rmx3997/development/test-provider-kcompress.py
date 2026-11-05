#!/usr/bin/python3
"""Execute actual OEM kcompress init/unwind bodies with host resource shims."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess

REPO = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
out = args.output.resolve()
out.mkdir(parents=True, exist_ok=False)
spec = importlib.util.spec_from_file_location('provider_test', REPO / 'rmx3997/development/test-provider.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
shim, cases = (REPO / 'rmx3997/provider/tests/kcompress-host.c').read_text().split('/* CASES */')
source = (REPO / 'rmx3997/provider/hybridswap_zram/kcompressd.c').read_text()
functions = ['init_write_queue', 'clean_bio_queue', 'kcompress_update',
             'stop_all_kcompressd_thread', 'kcompressd_init', 'kcompressd_exit']
fixture = out / 'kcompress.c'
fixture.write_text(shim + '\n'.join(helper.function(source, name) for name in functions) + cases)
commands = [['/usr/bin/clang', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
             str(fixture), '-o', str(out / 'test')], [str(out / 'test')]]
results = []
for i, command in enumerate(commands):
    argv = ['/usr/bin/python3', str(REPO / 'rmx3997/development/resource-guard.py'),
            '--log', str(out / f'{i}.log'), '--result', str(out / f'{i}.json'), '--'] + command
    result = subprocess.run(argv)
    results.append({'argv': argv, 'cwd': str(REPO), 'exit_code': result.returncode})
    if result.returncode: break
(out / 'results.json').write_text(json.dumps({'commands': results,
    'environment': {k: os.environ.get(k) for k in ('TMPDIR', 'PYTHONPYCACHEPREFIX', 'PATH')},
    'limits': 'Host allocation/FIFO/kthread/proc shims; actual source bodies, no kernel execution.'}, indent=2) + '\n')
raise SystemExit(results[-1]['exit_code'])
