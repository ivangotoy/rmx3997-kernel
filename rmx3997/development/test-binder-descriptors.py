#!/usr/bin/python3
"""Differentially execute actual baseline and staged source with host stubs."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

repo=Path(__file__).resolve().parents[2]
w=repo/'.worktrees/upstream-5.15.223'
cache=Path('/home/build/.cache/codex-work/rmx3997-feature-parity/binder-descriptor-fixture')
cache.mkdir(exist_ok=True)
old=subprocess.check_output(['git','-C',str(repo),'show','d7086885:drivers/android/binder.c'],text=True)
new=(w/'drivers/android/binder.c').read_text()
def body(text):
 start=text.index('static struct binder_ref *binder_get_ref_for_node_olocked(')
 opening=text.index('{',start);level=1;end=opening+1
 while level:
  if text[end]=='{':level+=1
  elif text[end]=='}':level-=1
  end+=1
 return text[start:end]
old_body=body(old).replace('binder_get_ref_for_node_olocked','binder_old')
new_body=body(new).replace('binder_get_ref_for_node_olocked','binder_new')
source=(repo/'rmx3997/development/binder-descriptor-fixture.c').read_text()
assert source.count('/* ACTUAL_FUNCTIONS */')==1
fixture=cache/'actual-allocators.c';fixture.write_text(source.replace('/* ACTUAL_FUNCTIONS */',old_body+'\n'+new_body))
argv=['/usr/bin/cc','-O2','-g','-Wall','-Wextra','-Werror','-Wno-misleading-indentation',str(fixture),'-o',str(cache/'test')]
env=os.environ.copy();env.update(TMPDIR=str(cache),PYTHONDONTWRITEBYTECODE='1')
subprocess.run(argv,check=True,env=env)
p=subprocess.run([str(cache/'test')],text=True,capture_output=True,env=env)
record={'baseline':'d7086885fca360b611a0e09686117dd344460cdc','upstream':'2316d138a3c3f2ec12cfb4b2f09ca9c95aa92ce5','old_function_sha256':hashlib.sha256(old_body.encode()).hexdigest(),'new_function_sha256':hashlib.sha256(new_body.encode()).hexdigest(),'argv':argv,'exit':p.returncode,'stdout':p.stdout,'stderr':p.stderr,'status':'PASS' if p.returncode==0 else 'FAIL','scope':'Actual extracted allocator functions with host BST/bitmap/callback/lock stubs; neither kernel runtime nor shipping module execution. Covers no-hook, no-op callback, changed start, callback-owned insertion, fast-toggle ownership, retry and existing descriptor sets.'}
(repo/'rmx3997/development/upstream-binder-descriptor-tests.json').write_text(json.dumps(record,indent=2)+'\n')
print(p.stdout);print(p.stderr);raise SystemExit(p.returncode)
