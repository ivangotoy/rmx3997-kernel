#!/usr/bin/python3
"""Guard and record a targeted build using the actual production argv/env."""
import json
import os
from pathlib import Path
import subprocess
import sys

stage = Path(sys.argv[1]).resolve()
label = sys.argv[2]
env = os.environ.copy()
env.update(json.loads((stage / 'build-environment.json').read_text()))
argv = json.loads((stage / 'build-argv.json').read_text())[:-2] + sys.argv[3:]
log = stage / (label + '.log')
if log.exists():
    raise FileExistsError(log)
sys.exit(subprocess.call(['/usr/bin/python3', str(stage / 'resource_guard.py'),
                         '--log', str(log), '--result', str(stage / (label + '.json')),
                         '--'] + argv, env=env))
