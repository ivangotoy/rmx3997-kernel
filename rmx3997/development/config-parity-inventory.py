#!/usr/bin/python3
"""Account for every literal config mention without treating mentions as support."""
from collections import defaultdict
import json
from pathlib import Path
import re

root = Path(__file__).resolve().parents[2]
d = root / 'rmx3997/development'
recipes = json.loads((d / 'recipe-inventory.json').read_text())
config = (d / 'delivery-core/production.config').read_text()
values = {}
for line in config.splitlines():
    if line.startswith('CONFIG_') and '=' in line:
        name, value = line.split('=', 1); values[name] = value
    elif line.startswith('# CONFIG_') and line.endswith(' is not set'):
        values[line[2:-11]] = 'n'
mentions = defaultdict(list)
for recipe in recipes['recipes']:
    for literal in recipe['config_mentions']:
        symbol = literal.split('=', 1)[0]
        mentions[symbol].append({'source': recipe['source'], 'commit': recipe['commit'],
                                 'path': recipe['path'], 'literal': literal})
entries = []
for symbol, sources in sorted(mentions.items()):
    expected = sorted(set(x['literal'].split('=', 1)[1] for x in sources if '=' in x['literal']))
    actual = values.get(symbol, 'absent')
    observation = 'PRESENT' if actual != 'absent' else 'ABSENT'
    if expected:
        observation = 'MENTION MATCHES COMPILED CONFIG' if actual in expected else 'UNRESOLVED DELTA OR OTHER-PROFILE OPTION'
    entries.append({'symbol': symbol, 'core_compiled_value': actual, 'literal_values_in_recipes': expected,
                    'observation': observation, 'sources': sources,
                    'semantic_validation': 'Use feature-status.txt and feature-specific evidence; config presence is not runtime proof. Cross-version/root-choice mentions are not automatically applicable.'})
record = {'scope': 'Every literal CONFIG mention in all retained workflow/action/patch/build-script recipes. Separate JSON configuration and fork-tool inventories remain part of the source closure.',
          'compiled_input': 'delivery-core/production.config, independently extracted from Image e2e7bdd3...fefa',
          'sources': recipes['sources'], 'recipe_count': len(recipes['recipes']),
          'symbol_count': len(entries), 'full_parity': False, 'entries': entries}
(d / 'config-parity-inventory.json').write_text(json.dumps(record, indent=2) + '\n')
print('Accounted recipe config symbols:', len(entries))
