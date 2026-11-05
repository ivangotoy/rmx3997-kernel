#!/usr/bin/python3
"""Run actual NoMount selector/child-accounting functions with host RCU stubs."""
import hashlib
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess

repo = Path(__file__).resolve().parents[2]
root = Path('/home/build/.cache/codex-work/rmx3997-full-features-20261104')
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, default=root / 'nomount-primary-host')
out = parser.parse_args().output
out.mkdir(exist_ok=False)
spec = importlib.util.spec_from_file_location('functions', Path(__file__).with_name('test-full-feature-components.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
source = repo / 'fs/nomount/nomount.c'
text = source.read_text()
funcs = ''.join(module.function(text, name) for name in [
    'nm_select_rule', 'nm_publish_child_view_locked', 'nm_inject_child_locked', 'nm_delete_child_locked'])
shim = r'''
typedef uint16_t u16;
struct nm_rule {unsigned int target_uid,uid_end,deny_start,deny_end;};
struct nm_rule_array {int count; struct nm_rule rules[2];};
struct nm_leaf;
struct nm_child {u32 hash,bloom_hash;struct nm_leaf *leaf;};
struct nm_child_array {int count,bloom_words;u64 bloom[1];struct nm_child entries[8];};
struct nm_dir_node {struct nm_child_array *children;unsigned int readdir_count;void *pinned_dentry;int refs;};
struct nm_leaf {struct nm_rule_array *rules;struct nm_dir_node *parent_dir;u16 child_len;bool show;};
#define rcu_dereference_check(v,lock) (v)
#define rcu_dereference_protected(v,lock) (v)
#define rcu_assign_pointer(v,n) ((v)=(n))
#define WRITE_ONCE(v,n) ((v)=(n))
#define nm_entries(a) ((a)->entries)
#define nm_bsearch_child(a,name,len,hash,pos) NULL
#define full_name_hash(seed,name,len) 0
#define nm_qhash(name,len) 0
#define nm_bloom_words_for(count) 0
#define nm_bloom_set(a,h) ((void)0)
#define nm_rules_need_readdir(leaf,rules) ((leaf)->show)
#define atomic_inc(ref) (++*(ref))
#define kfree_rcu(ptr,member) free(ptr)
#define dput(ptr) ((void)(ptr))
#define ERR_PTR(err) ((void *)(intptr_t)(err))
static int fail_alloc;
static struct nm_child_array *nm_alloc_child_array(int count,int words) {
    if(fail_alloc)return NULL;
    struct nm_child_array *a=calloc(1,sizeof(*a));assert(a);a->count=count;return a;
}
'''
tests = r'''
int main(void) {
    struct nm_rule_array rules={.count=2,.rules={{0,0,55,66},{100,200,100,110}}};
    struct nm_leaf leaf={.rules=&rules,.show=true};
    for(unsigned int uid=0;uid<=300;uid++) {
        struct nm_rule *expected = uid>=111 && uid<=200 ? &rules.rules[1] :
            uid>=55 && uid<=66 ? NULL : &rules.rules[0];
        assert(nm_select_rule(&leaf,uid)==expected);
    }
    for(int i=0;i<1000;i++) {
        struct nm_dir_node dir={0};leaf.parent_dir=NULL;
        assert(!nm_inject_child_locked(&dir,&leaf,"file",4));
        assert(dir.readdir_count==1 && dir.children && dir.refs==1);
        assert(nm_delete_child_locked(&leaf,false)==&dir);
        assert(dir.readdir_count==0 && !dir.children);
    }
    struct nm_dir_node dir={0};leaf.parent_dir=NULL;fail_alloc=1;
    assert(nm_inject_child_locked(&dir,&leaf,"file",4)==-ENOMEM);
    assert(!dir.children && !dir.readdir_count && !leaf.parent_dir);
    puts("PASS:301 UID boundary/deny/fallback cases;1000 actual child add/delete cycles; allocation-failure invariants");
}
'''
fixture = out / 'nomount.c'
fixture.write_text(module.PRELUDE + shim + funcs + tests)
argv = ['/usr/bin/cc', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
        '-Wno-sign-compare', str(fixture), '-o', str(out / 'nomount')]
env = dict(os.environ, TMPDIR=str(root), PYTHONPYCACHEPREFIX=str(root / 'pycache'))
with (out / 'result.log').open('x') as stream:
    compiled = subprocess.run(argv, cwd=repo, env=env, stdout=stream, stderr=subprocess.STDOUT)
    ran = subprocess.run([str(out / 'nomount')], cwd=repo, env=env, stdout=stream,
                         stderr=subprocess.STDOUT) if not compiled.returncode else None
(out / 'result.json').write_text(json.dumps({
    'scope': __doc__ + ' Not kernel/RCU runtime or whole NoMount upgrade acceptance.',
    'compile_argv': argv, 'run_argv': [str(out / 'nomount')], 'cwd': str(repo),
    'environment_overrides': {k: env[k] for k in ['TMPDIR', 'PYTHONPYCACHEPREFIX']},
    'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
    'compile_exit': compiled.returncode, 'run_exit': ran.returncode if ran else None,
    'log': str(out / 'result.log')}, indent=2) + '\n')
raise SystemExit(compiled.returncode or ran.returncode)
