#!/usr/bin/python3
"""Offline negative tests of actual freeze/config validators, disk fixtures only."""
import argparse,hashlib,importlib.util,json,pathlib
p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();out=pathlib.Path(a.output);out.mkdir(exist_ok=False)
spec=importlib.util.spec_from_file_location('contracts',pathlib.Path(__file__).with_name('full-feature-contracts.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
file=out/'source.c';file.write_text('retained input\n');record={'source_sha256':{'source.c':m.sha(file.read_bytes())}};m.verify_sources(record,out)
failures=0
for mutation in ['changed','missing']:
 if mutation=='changed':file.write_text('changed input\n')
 else:file.unlink()
 try:m.verify_sources(record,out)
 except ValueError:failures+=1
 else:raise AssertionError(mutation+' accepted')
actual=m.parse_config(pathlib.Path('/home/build/.cache/codex-work/rmx3997-full-features-20261104/components197/out/.config').read_text());expected={'CONFIG_BPF_STREAM_PARSER':'y'};actual.update(expected)
m.verify_config(expected,actual)
for key,value in [('CONFIG_KSU','m'),('CONFIG_CFI_CLANG','n'),('CONFIG_LTO_CLANG_FULL','n'),('CONFIG_ZRAM','y'),('CONFIG_F2FS_FS_DEDUP','n'),('CONFIG_ARM64_4K_PAGES','n'),('CONFIG_BPF_STREAM_PARSER','n')]:
 mutated=dict(actual);mutated[key]=value
 try:m.verify_config(expected,mutated)
 except ValueError:failures+=1
 else:raise AssertionError(key+' accepted')
result={'result':'PASS','negative_mutations_rejected':failures,'scope':'Actual source freeze and requested/protected configuration validators only; no upstream or runtime proof'}
(out/'results.json').write_text(json.dumps(result,indent=2)+'\n');print(result)
