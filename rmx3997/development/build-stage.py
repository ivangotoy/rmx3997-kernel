#!/usr/bin/python3
"""Run the retained hard-abort guard, preserving distinct logs per attempt."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

stage = Path(sys.argv[1]).resolve()
label = sys.argv[2]
log = stage / (label + '.log')
if log.exists():
    raise FileExistsError(log)
# This host also runs independent Forgejo kernel builds. Do not overlap LTO
# merely because a preceding light compile fitted in memory.
deadline = time.monotonic() + 900
while True:
    info = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
    available = int(info['MemAvailable'].split()[0]) * 1024
    peers = []
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            if (process / 'comm').read_text().strip() == 'ld.lld':
                peers.append(int(process.name))
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            pass
    if available >= 22 * 1024**3 and not peers:
        break
    print('Waiting for LTO memory: available_GiB=%.2f peer_linkers=%s' %
          (available / 1024**3, peers), flush=True)
    if time.monotonic() >= deadline:
        raise SystemExit('BLOCKED: competing host linkers/memory; no build started')
    time.sleep(15)
env = os.environ.copy()
env.update(json.loads((stage / 'build-environment.json').read_text()))
os.chdir(stage / 'kernel/common')
result = stage / 'build-execution.json'
if result.exists():
    result.rename(stage / (label + '-prior-build-execution.json'))
argv = ['/usr/bin/python3', str(Path(__file__).resolve().with_name('resource-guard.py')), '--log', str(log),
        '--result', str(result), '--'] + json.loads((stage / 'build-argv.json').read_text())
sys.exit(subprocess.call(argv, env=env))
