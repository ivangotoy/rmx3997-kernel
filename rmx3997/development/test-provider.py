#!/usr/bin/python3
"""Compile actual provider bodies with host ownership shims and real codecs.

Does not certify kernel locking/RCU, ARM64 execution or OEM hybrid UFS I/O.
All compilation is under the retained tested resource guard.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

REPO = Path(__file__).resolve().parents[2]
PROVIDER = REPO / 'rmx3997/provider/hybridswap_zram'


def function(text, name):
    match = re.search(r'(?m)^(?:static )?(?:inline )?[\w *]+\b' + name +
                      r'\([^;{]*\)\n\{', text)
    if not match:
        raise ValueError('Missing actual function: ' + name)
    start = match.start()
    depth = 1
    i = match.end()
    while depth:
        if text[i] == '{': depth += 1
        elif text[i] == '}': depth -= 1
        i += 1
    return text[start:i] + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    scratch = Path(os.environ['TMPDIR']).resolve()
    fstype = subprocess.run(['findmnt', '-n', '-o', 'FSTYPE', '--target', str(scratch)],
                            capture_output=True, text=True, check=True).stdout.strip()
    if fstype in ('tmpfs', 'ramfs'):
        raise ValueError('Disk-backed task TMPDIR required, got %s' % fstype)
    drv = (PROVIDER / 'zram_drv.c').read_text()
    header = (PROVIDER / 'zram_drv.h').read_text()
    hybrid = (PROVIDER / 'hybridswap/hybridswap.c').read_text()
    parts = [(REPO / 'rmx3997/provider/tests/host-shim.h').read_text()]
    parts += [function(header, name) for name in
              ('zram_get_priority', 'zram_set_priority', 'zram_comp')]
    parts += [function(hybrid, 'hybridswap_recompress_account')]
    parts += [function(drv, name) for name in
              ('zram_free_page', 'zram_meta_free', '__zram_bvec_read', '__zram_bvec_write')]
    parts += [(PROVIDER / 'zram_recompress.c').read_text(),
              function(drv, 'zram_reset_device'),
              function(hybrid, 'move_to_hybridswap'),
              function(hybrid, '__move_to_zram'),
              (REPO / 'rmx3997/provider/tests/host-cases.c').read_text()]
    source = out / 'actual-provider-host.c'
    source.write_text('\n'.join(parts))
    commands = [
        ['/usr/bin/clang', '-D_GNU_SOURCE', '-O1', '-g', '-fsanitize=address,undefined',
         '-fno-omit-frame-pointer', '-fno-sanitize-recover=all', str(source), '-llz4', '-lzstd', '-o', str(out / 'host-test')],
        [str(out / 'host-test')],
    ]
    results = []
    for index, argv in enumerate(commands):
        guarded = ['/usr/bin/python3', str(REPO / 'rmx3997/development/resource-guard.py'),
                   '--log', str(out / f'{index}.log'), '--result', str(out / f'{index}.json'), '--'] + argv
        result = subprocess.run(guarded)
        results.append({'argv': guarded, 'cwd': str(REPO), 'exit_code': result.returncode})
        if result.returncode: break
    record = {'commands': results, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'environment': {key: os.environ.get(key) for key in ('TMPDIR', 'PYTHONPYCACHEPREFIX', 'PATH')},
              'limits': 'Host shims plus real liblz4/libzstd; not real kernel/ARM64/UFS proof.'}
    (out / 'results.json').write_text(json.dumps(record, indent=2) + '\n')
    return results[-1]['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
