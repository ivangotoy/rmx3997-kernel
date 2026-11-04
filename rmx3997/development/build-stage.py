#!/usr/bin/python3
"""Run the retained hard-abort guard, preserving distinct logs per attempt."""
import json
import os
from pathlib import Path
import subprocess
import sys

stage = Path(sys.argv[1]).resolve()
label = sys.argv[2]
log = stage / (label + '.log')
if log.exists():
    raise FileExistsError(log)
env = os.environ.copy()
env.update(json.loads((stage / 'build-environment.json').read_text()))
os.chdir(stage / 'kernel/common')
result = stage / 'build-execution.json'
if result.exists():
    result.rename(stage / (label + '-prior-build-execution.json'))
argv = ['/usr/bin/python3', str(stage / 'resource_guard.py'), '--log', str(log),
        '--result', str(result), '--'] + json.loads((stage / 'build-argv.json').read_text())
sys.exit(subprocess.call(argv, env=env))
