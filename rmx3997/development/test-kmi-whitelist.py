#!/usr/bin/python3
"""Focused actual whitelist producer/autoksyms regression on disk fixtures."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('whitelist', REPO/'rmx3997/development/prepare-kmi-whitelist.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def main(out):
    out.mkdir(parents=True, exist_ok=False)
    canonical = REPO/'rmx3997/config/abi-symbol-list.txt'
    current = canonical.read_bytes()
    old = out/'inherited.raw'
    old.write_bytes(b'\n'.join(v for v in current.splitlines() if v != b'cgroup_rm_cftypes')+b'\n')
    stage = out/'stage';(stage/'out').mkdir(parents=True)
    config = stage/'out/.config'
    config.write_text('CONFIG_TRIM_UNUSED_KSYMS=y\nCONFIG_MODVERSIONS=y\nCONFIG_MODULE_SIG_PROTECT=y\n'
                      'CONFIG_CFI_CLANG=y\nCONFIG_UNUSED_KSYMS_WHITELIST="'+str(old)+'"\n')
    old_bytes = old.read_bytes()
    record = m.bind(stage, out/'binding')
    assert record['added_symbols'] == ['cgroup_rm_cftypes']
    assert record['removed_symbols'] == [] and old.read_bytes() == old_bytes
    assert set(m.symbols(current)) == m.symbols((stage/'out/abi_symbollist.raw').read_bytes())
    assert str(stage/'out/abi_symbollist.raw') in config.read_text()
    # Run the real shell consumer against the generated list, not a reimplementation.
    inc = stage/'out/include/config';inc.mkdir(parents=True)
    (inc/'auto.conf').write_text(config.read_text())
    subprocess.run(['/bin/sh',str(REPO/'scripts/gen_autoksyms.sh'),str(out/'autoksyms.h')],
                   cwd=stage/'out',check=True)
    header=(out/'autoksyms.h').read_text()
    assert '#define __KSYM_cgroup_rm_cftypes 1\n' in header
    for name in m.symbols(old_bytes):assert '#define __KSYM_'+name+' 1\n' in header
    # Losing an existing symbol and disabled trim both reject before writes.
    before=config.read_bytes();snapshot=(stage/'out/abi_symbollist.raw').read_bytes()
    try:m.bind(stage,out/'loss-rejected',old)
    except ValueError as e:assert 'loses inherited' in str(e)
    else:raise AssertionError('symbol loss accepted')
    assert config.read_bytes()==before and (stage/'out/abi_symbollist.raw').read_bytes()==snapshot
    config.write_bytes(before.replace(b'CONFIG_TRIM_UNUSED_KSYMS=y',b'CONFIG_TRIM_UNUSED_KSYMS=n'))
    try:m.bind(stage,out/'trim-rejected')
    except ValueError as e:assert 'protections' in str(e)
    else:raise AssertionError('disabled trim accepted')
    assert not (out/'loss-rejected').exists() and not (out/'trim-rejected').exists()
    (out/'results.json').write_text(json.dumps({'status':'PASS','real_flatten':str(m.FLATTEN),
        'real_autoksyms':str(REPO/'scripts/gen_autoksyms.sh'),'existing_symbols_preserved':len(m.symbols(old_bytes)),
        'added':['cgroup_rm_cftypes'],'loss_rejected_before_write':True,'disabled_trim_rejected':True,
        'limits':'Real producer/consumer on disk fixtures, no kernel link/module ABI/runtime proof'},indent=2)+'\n')
    print('PASS real flatten/autoksyms, inherited symbols retained, config bound, loss/trim fail closed')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);main(p.parse_args().output.resolve())
