#!/usr/bin/python3
"""Generate and bind the current stage's trim whitelist; never edit its ancestor.

Run before olddefconfig/prepare and a normal guarded Image build. Existing
binaries remain evidence for their previous config, not this prepared config.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]
FLATTEN = Path('/home/build/Downloads/rea-lk-analysis/rmx3997-custom-gki-build/kernel/build/kernel/abi/flatten_symbol_list')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def values(text):
    return dict(line.split('=', 1) for line in text.splitlines()
                if line.startswith('CONFIG_') and '=' in line)


def symbols(raw):
    names = raw.decode().splitlines()
    if not names or any(not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', n) for n in names):
        raise ValueError('Expected canonical flat symbol list')
    if len(set(names)) != len(names):
        raise ValueError('Duplicate whitelist symbol')
    return set(names)


def bind(stage, evidence, source=REPO / 'rmx3997/config/abi-symbol-list.txt'):
    stage = stage.resolve(strict=True)
    evidence = evidence.resolve()
    config = stage / 'out/.config'
    before = config.read_bytes()
    old = values(before.decode())
    required = ['CONFIG_TRIM_UNUSED_KSYMS', 'CONFIG_MODVERSIONS', 'CONFIG_MODULE_SIG_PROTECT']
    if any(old.get(k) != 'y' for k in required):
        raise ValueError('Trim/module protections must already be enabled')
    configured = old.get('CONFIG_UNUSED_KSYMS_WHITELIST', '')
    if not re.fullmatch(r'"/[^"\n]+"', configured):
        raise ValueError('Expected absolute inherited whitelist path')
    previous = Path(configured[1:-1])
    previous_bytes = previous.read_bytes()
    source_bytes = source.read_bytes()
    prior_symbols, current_symbols = symbols(previous_bytes), symbols(source_bytes)
    if not prior_symbols <= current_symbols:
        raise ValueError('Current whitelist loses inherited symbols: ' + ','.join(sorted(prior_symbols-current_symbols)))
    target = stage / 'out/abi_symbollist.raw'
    structured = stage / 'abi/abi_symbollist.current'
    if target.is_symlink() or structured.is_symlink():
        raise ValueError('Refuse symlink whitelist outputs')
    # Use the same structured -> raw upstream producer as build.sh. The project
    # already retains the approved flattened input; reconstruct one section
    # without changing names, namespaces, exports, CRCs or protection lists.
    text = '[abi_symbol_list]\n' + ''.join('  ' + s + '\n' for s in sorted(current_symbols))
    argv = [sys.executable, str(FLATTEN)]
    raw = subprocess.check_output(argv, input=text.encode())
    if symbols(raw) != current_symbols:
        raise ValueError('Official flatten output differs from canonical source')
    if evidence.exists():
        raise FileExistsError(evidence)
    evidence.mkdir(parents=True)
    (evidence / 'config.before').write_bytes(before)
    (evidence / 'whitelist.before').write_bytes(previous_bytes)
    (stage / 'abi').mkdir(exist_ok=True)
    structured.write_text(text)
    target.write_bytes(raw)
    set_config = [str(REPO / 'scripts/config'), '--file', str(config),
                  '--set-str', 'UNUSED_KSYMS_WHITELIST', str(target)]
    subprocess.run(set_config, check=True)
    after = values(config.read_text())
    if {k:v for k,v in after.items() if k != 'CONFIG_UNUSED_KSYMS_WHITELIST'} != {
            k:v for k,v in old.items() if k != 'CONFIG_UNUSED_KSYMS_WHITELIST'}:
        raise ValueError('Unexpected config change')
    record = {'stage': str(stage), 'source': str(source), 'source_sha256': sha(source_bytes),
              'inherited_whitelist': str(previous), 'inherited_sha256': sha(previous_bytes),
              'structured': str(structured), 'structured_sha256': sha(text.encode()),
              'generated_whitelist': str(target), 'generated_sha256': sha(raw),
              'preserved_symbols': len(prior_symbols), 'generated_symbols': len(current_symbols),
              'added_symbols': sorted(current_symbols-prior_symbols), 'removed_symbols': [],
              'flatten_argv': argv, 'flatten_tool_sha256': sha(FLATTEN.read_bytes()),
              'set_config_argv': set_config, 'config_before_sha256': sha(before),
              'config_after_sha256': sha(config.read_bytes()),
              'next': 'Run guarded olddefconfig/prepare; inspect actual gen_autoksyms output. Normal Image autoksyms_recursive must rebuild/link changed export; no linked success claimed.'}
    (evidence / 'binding.json').write_text(json.dumps(record, indent=2)+'\n')
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(bind(args.stage, args.evidence), indent=2))
