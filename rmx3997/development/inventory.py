#!/usr/bin/python3
"""Capture recipes at immutable source revisions; pending is never parity."""
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ROOT / '.cache/parity-sources'
baseline = (ROOT / 'rmx3997/config/production.config').read_text()
result = {'baseline': 'd7086885fca360b611a0e09686117dd344460cdc',
          'sources': {}, 'recipes': [], 'status': 'IN PROGRESS; not full parity'}
for name in ('wild-gki', 'wild-oneplus', 'aimax-fork', 'kernel-patches'):
    source = SOURCES / name
    commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    result['sources'][name] = commit
    files = sorted(set(source.glob('.github/**/*.yml')) | set(source.glob('.github/**/*.yaml')) |
                   set(source.glob('build-gki-*.sh')) | set(source.glob('.github/patches/*.patch')) |
                   set(source.glob('common/**/*.patch')) | set(source.glob('oneplus/**/*.patch')))
    for path in files:
        text = path.read_text(errors='replace')
        flags = sorted(set(re.findall(r'CONFIG_[A-Z0-9_]+(?:=(?:[ynm]|[0-9]+|"[^"\n]*"))?', text)))
        stages = [s.strip() for s in re.findall(r'^\s*- name:\s*(.+)$', text, re.M)]
        patches = sorted(set(re.findall(r'[A-Za-z0-9_./${}-]+\.patch', text)))
        result['recipes'].append({'source': name, 'commit': commit, 'path': str(path.relative_to(source)),
                                  'stages': stages, 'config_mentions': flags, 'patch_mentions': patches,
                                  'baseline_config_matches': [f for f in flags if '=' in f and f in baseline.splitlines()],
                                  'review': 'PENDING: recipe references are inventory, not integration or test evidence'})
(ROOT / 'rmx3997/development/recipe-inventory.json').write_text(json.dumps(result, indent=2) + '\n')
print('sources', result['sources'])
print('recipe count', len(result['recipes']))
