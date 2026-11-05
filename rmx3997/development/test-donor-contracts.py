#!/usr/bin/python3
"""Focused PM/logging function tests and actual Unicode donor comparison.

The Unicode comparison uses the real normalization tables and source functions.
PM and logging use host shims; none of these tests establish kernel execution.
"""
import hashlib
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess

repo = Path(__file__).resolve().parents[2]
root = Path('/home/build/.cache/codex-work/rmx3997-full-features-20261104')
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, default=root / 'donor-contract-tests')
parser.add_argument('--skip-pm', action='store_true')
args = parser.parse_args()
out = args.output
out.mkdir(exist_ok=False)
env = dict(os.environ, TMPDIR=str(root), PYTHONPYCACHEPREFIX=str(root / 'pycache'))
spec = importlib.util.spec_from_file_location('component_functions', Path(__file__).with_name('test-full-feature-components.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
records = []


def execute(label, body):
    src = out / (label + '.c')
    exe = out / label
    src.write_text(body)
    argv = ['/usr/bin/cc', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
            '-Wno-unused-variable', '-Wno-sign-compare', str(src), '-o', str(exe)]
    with (out / (label + '.log')).open('x') as log:
        built = subprocess.run(argv, cwd=repo, env=env, stdout=log, stderr=subprocess.STDOUT)
        if built.returncode:
            raise RuntimeError((label, 'compile', built.returncode))
        ran = subprocess.run([str(exe)], cwd=repo, env=env, capture_output=True, text=True, timeout=20)
        log.write(ran.stdout + ran.stderr)
        if ran.returncode:
            raise RuntimeError((label, 'run', ran.returncode))
    records.append({'label': label, 'compile_argv': argv, 'run_argv': [str(exe)],
                    'cwd': str(repo), 'compile_exit': 0, 'run_exit': ran.returncode,
                    'source_sha256': hashlib.sha256(src.read_bytes()).hexdigest(),
                    'log': str(out / (label + '.log'))})
    return ran.stdout


function = module.function
pm = (repo / 'drivers/base/power/wakeup.c').read_text()
log = (repo / 'kernel/printk/printk.c').read_text()
if not args.skip_pm:
    execute('pm-and-log', module.PRELUDE + r'''
    static int pm_abort_suspend, wake_count, allow_log;
    static int atomic_inc_return_relaxed(int *x) {return ++*x;}
    static int atomic_dec_if_positive(int *x) {if (*x > 0) --*x; return *x;}
    static void s2idle_wake(void) {wake_count++;}
    #define HZ 100
    #define DEFINE_RATELIMIT_STATE(name,interval,burst) int name
    #define __ratelimit(state) allow_log
    ''' + function(pm, 'pm_system_wakeup') + function(pm, 'pm_system_cancel_wakeup') +
            function(log, 'devkmsg_suppress_service_noise') + r'''
    int main(void) {
        for(int i=0;i<1000;i++){pm_system_wakeup();}
        assert(wake_count==1);
        for(int i=0;i<1000;i++){pm_system_cancel_wakeup();}
        assert(pm_abort_suspend==0);
        pm_system_wakeup();assert(wake_count==2);
        allow_log=1;assert(!devkmsg_suppress_service_noise(6,"healthd: sample"));
        allow_log=0;assert(devkmsg_suppress_service_noise(6,"healthd: sample"));
        assert(devkmsg_suppress_service_noise(7,"logd: sample"));
        assert(!devkmsg_suppress_service_noise(4,"healthd: failure"));
        assert(!devkmsg_suppress_service_noise(6,"critical failure mentioning logd"));
        assert(!devkmsg_suppress_service_noise(6,"healthdebug"));
        puts("PASS wake transition/cancel and service-prefix/severity/rate-limit decisions");
    }
    ''')

normalizer = (repo / 'fs/unicode/utf8-norm.c').read_text()
header = (repo / 'fs/unicode/utf8n.h').read_text()
header = re.sub(r'^#include.*\n', '', header, flags=re.M)
base = normalizer.replace('#include "utf8n.h"', '').replace(
    '#include "utf8data.h"', '#include "' + str(repo / 'fs/unicode/utf8data.h_shipped') + '"')
patch_path = repo / '.cache/parity-sources/kernel-patches/common/unicode_bypass_fix_6.1-.patch'
patch = patch_path.read_text().split('@@', 2)[2].split('\n', 1)[1]
lines = [line for line in patch.splitlines(True) if line[:1] in [' ', '+', '-']]
old = ''.join(line[1:] for line in lines if line[:1] in [' ', '-'])
new = ''.join(line[1:] for line in lines if line[:1] in [' ', '+'])
assert base.count(old) == 1
donor = base.replace(old, new)
prelude = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <sys/types.h>
typedef uint8_t u8;
#define EXPORT_SYMBOL(name)
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
'''
vectors = [b'ab', b'a\xe2\x80\x8bb', b'a\xc2\xadb', b'a\xe2\x81\xa0b', b'a\xef\xb8\x8fb']
main = '\nint main(void) {\n'
for index, vector in enumerate(vectors):
    main += 'char s%d[]={%s};\n' % (index, ','.join(str(v) for v in vector + b'\0'))
    main += '{struct utf8cursor c; int v, count=0; if(utf8ncursor(&c,utf8nfdicf(utf8version_latest()),s%d,%d))return 2; ' % (index, len(vector))
    main += 'while((v=utf8byte(&c))>0){if(++count>64)return 3;printf("%02x",v);}if(v<0)return 4;puts("");}\n'
main += 'return 0;}\n'
baseline = execute('unicode-baseline', prelude + header + base + main).splitlines()
changed = execute('unicode-donor', prelude + header + donor + main).splitlines()
assert baseline == ['6162'] * len(vectors)
assert any(a != b for a, b in zip(baseline, changed))
record = {'scope': __doc__, 'records': records,
          'environment_overrides': {k: env[k] for k in ['TMPDIR', 'PYTHONPYCACHEPREFIX']},
          'unicode': {'source_sha256': hashlib.sha256(normalizer.encode()).hexdigest(),
                      'donor_patch_sha256': hashlib.sha256(patch_path.read_bytes()).hexdigest(),
                      'inputs_hex': [v.hex() for v in vectors], 'baseline_normalized_hex': baseline,
                      'donor_normalized_hex': changed,
                      'decision': 'Raw donor changes existing casefold filename equivalence; not applied under persistent /data compatibility requirement. A filesystem-independent security-policy fix needs a concrete caller contract.'}}
(out / 'results.json').write_text(json.dumps(record, indent=2) + '\n')
print('PASS: demonstrated actual Unicode donor filename-equivalence change; PM/log results retained separately when skipped')
