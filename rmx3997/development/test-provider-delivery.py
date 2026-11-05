#!/usr/bin/python3
"""Narrow actual loader/hook/transaction tests with explicit host adapters.

The host never calls finit_module and never accesses phone partitions. The
ARM64 loader is compiled, not executed. Real preinit/module/UFS tests remain
the parent production-Image guest gate.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess

REPO = Path(__file__).resolve().parents[2]
TASK = Path('/home/build/.cache/codex-work/rmx3997-full-features-20261104')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--only-storage', action='store_true')
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    controlled_env = json.loads((TASK / 'components197/build-environment.json').read_text())
    env = {**os.environ, **controlled_env}
    commands = []

    def guarded(argv, label):
        full = ['/usr/bin/python3', str(REPO / 'rmx3997/development/resource-guard.py'),
                '--log', str(out / (label + '.log')), '--result', str(out / (label + '.json')), '--'] + argv
        result = subprocess.run(full, env=env)
        commands.append({'argv': full, 'cwd': str(REPO), 'exit_code': result.returncode})
        if result.returncode:
            raise RuntimeError('Guarded fixture failed: ' + label)

    if args.only_storage:
        assets = out / 'assets'
        assets.mkdir()
        for name in ('provider-loader', 'provider.ko', 'preinit.conf'):
            (assets / name).write_text('Storage fixture: ' + name)
        import shutil
        shutil.copyfile('/home/build/Downloads/rea-lk-analysis/oem-module-compatibility-20261103/filesystems/vendor_dlkm_b/lib/modules/oplus_bsp_hybridswap_zram.ko', assets / 'original-provider.ko')
        dependencies = ['oplus_bsp_mm_osvelte.ko', 'mtk_disp_notify.ko', 'oplus_bsp_kshrink_slabd.ko',
                        'oplus_bsp_eas_opt.ko', 'oplus_bsp_sched_assist.ko', 'oplus_schedinfo.ko', 'oplus_bsp_zsmalloc.ko']
        for name in dependencies:
            (assets / name).write_text('Disk dependency fixture: ' + name)
        (assets / 'provider-dependencies.sha256').write_text(''.join(
            hashlib.sha256((assets / name).read_bytes()).hexdigest() + '  ' + name + '\n' for name in sorted(dependencies)))
        shell = out / 'storage-fixture.sh'
        hashes = {name: hashlib.sha256((assets / name).read_bytes()).hexdigest()
                  for name in ('provider-loader', 'provider.ko', 'preinit.conf')}
        preamble = '\n'.join(key + '=' + value for key, value in {
            'PROVIDER_LOADER_SHA256': hashes['provider-loader'],
            'PROVIDER_MODULE_SHA256': hashes['provider.ko'],
            'PROVIDER_CONF_SHA256': hashes['preinit.conf'],
            'PROVIDER_DEPS_SHA256': hashlib.sha256((assets / 'provider-dependencies.sha256').read_bytes()).hexdigest(),
        }.items()) + '\n'
        shell.write_text(preamble + '''. "$1"
PROVIDER_ASSETS=$2/assets
PROVIDER_KSU=$2/metadata/ksu
PROVIDER_STAGE=$PROVIDER_KSU/stage
PROVIDER_ACTIVE=$PROVIDER_KSU/preinit/rmx3997-provider
platform_hash() {
 if [ "$1" = /vendor_dlkm/lib/modules/oplus_bsp_hybridswap_zram.ko ];then
  printf '%s\\n' 66c8904aca7e43f54cd4c7ed7c7a8df358031acd6885f569fefb2a656e17d302
 else /usr/bin/sha256sum "$1" | /usr/bin/cut -d ' ' -f 1;fi
}
provider_assets_verify "$PROVIDER_ASSETS" || exit 1
provider_stage && provider_stage_verify && provider_activate || exit 2
[ -d "$PROVIDER_ACTIVE" ] && [ ! -e "$PROVIDER_STAGE" ] || exit 3
provider_restore && provider_restore_verify || exit 4
[ -d "$PROVIDER_STAGE" ] || exit 5
printf tampered > "$PROVIDER_STAGE/provider.ko"
if provider_stage_verify;then exit 6;fi
rm "$PROVIDER_STAGE/provider.ko"
ln -s "$PROVIDER_ASSETS/provider.ko" "$PROVIDER_STAGE/provider.ko"
if provider_stage_verify;then exit 7;fi
rm "$PROVIDER_STAGE/provider.ko"
cp "$PROVIDER_ASSETS/provider.ko" "$PROVIDER_STAGE/provider.ko"
rm "$PROVIDER_STAGE/original-provider.ko"
if provider_stage_verify;then exit 8;fi
printf 'PASS actual disk staging/activation/rollback; corruption, symlink and missing-original rejection\\n'
''')
        guarded(['/bin/sh', str(shell), str(REPO / 'rmx3997/provider/provider-android.sh'), str(out)], 'storage-run')
        for name in ('provider-android.sh', 'provider-transaction.sh', 'provider-install-entry.sh'):
            subprocess.run(['/bin/sh', '-n', str(REPO / 'rmx3997/provider' / name)], check=True)
        (out / 'results.json').write_text(json.dumps({'commands': commands, 'environment': controlled_env,
            'limits': 'Actual adapter file operations on ext4 fixture; platform identity/boot writes are shims, no phone operations.'}, indent=2) + '\n')
        return

    notes = out / 'notes'
    notes.write_bytes(b'fixture kernel notes, not a production Image')
    inputs = []
    for index in range(3):
        path = out / ('module' + str(index))
        path.write_bytes(('fixture module ' + str(index)).encode())
        path.chmod(0o600)
        inputs.append((str(path), 'dep' + str(index), hashlib.sha256(path.read_bytes()).hexdigest()))
    header = '#define PROVIDER_KERNEL_NOTES_SHA256 ' + json.dumps(hashlib.sha256(notes.read_bytes()).hexdigest()) + '\n'
    header += 'static const struct provider_input provider_inputs[] = {\n'
    header += ',\n'.join('{' + ','.join(json.dumps(s) for s in row) + '}' for row in inputs) + '\n};\n'
    (out / 'provider-inputs.h').write_text(header)
    utility = out / 'hash-utility'
    utility.write_text('#!/bin/sh\n[ "$1" = sha256sum ] || exit 1\nexec /usr/bin/sha256sum\n')
    utility.chmod(0o700)
    modules = out / 'sys-modules'
    modules.mkdir()
    hook = out / 'loader-test-hook.h'
    hook.write_text('''#include <sys/stat.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <errno.h>
static uid_t test_uid(void) { return 0; }
static int test_fstat(int fd, struct stat *st) {
 int r=fstat(fd,st); if(!r) st->st_uid=getenv("BAD_OWNER")?1:0; return r;
}
static int test_load(int fd) {
 static int count; char c; FILE *log=fopen(getenv("LOAD_LOG"),"a");
 if(!log)return -1; if(read(fd,&c,1)!=1){fclose(log);return -1;}
 fprintf(log,"%d %c\\n",++count,c);fclose(log);
 if(getenv("FAIL_LOAD")&&count==atoi(getenv("FAIL_LOAD"))){errno=ENOEXEC;return -1;}
 return 0;
}
#define getuid test_uid
#define fstat test_fstat
#define PROVIDER_LOAD(fd) test_load(fd)
''')
    source = REPO / 'rmx3997/provider/preinit-loader.c'
    host = out / 'loader-host'
    guarded(['/usr/bin/clang', '-O2', '-Wall', '-Wextra', '-Werror', '-include', str(hook),
             '-I' + str(out), '-DHASH_PROGRAM=' + json.dumps(str(utility)),
             '-DNOTES_PATH=' + json.dumps(str(notes)),
             '-DMODULES_PATH=' + json.dumps(str(modules) + '/'),
             str(source), '-o', str(host)], 'loader-host-build')
    loader_results = []
    log = out / 'load-events'

    def run_loader(name, expected, loads, overrides=None):
        if log.exists(): log.unlink()
        local_env = {**env, 'KSU_PREINIT': '1', 'LOAD_LOG': str(log), **(overrides or {})}
        result = subprocess.run([str(host)], env=local_env, capture_output=True, text=True, timeout=10)
        events = log.read_text().splitlines() if log.exists() else []
        assert result.returncode == expected and len(events) == loads, (name, result.returncode, result.stderr, events)
        loader_results.append({'case': name, 'exit_code': result.returncode, 'simulated_finit_calls': len(events)})

    run_loader('complete authenticated closure', 0, 3)
    original_notes = notes.read_bytes()
    notes.write_bytes(b'wrong notes')
    run_loader('wrong kernel notes', 1, 0)
    notes.write_bytes(original_notes)
    module = Path(inputs[1][0]); original_module = module.read_bytes()
    module.write_bytes(b'corruption')
    run_loader('bad dependency hash causes no loads', 1, 0)
    module.write_bytes(original_module)
    module.chmod(0o622)
    run_loader('writable module rejected', 1, 0)
    module.chmod(0o600)
    run_loader('wrong owner rejected', 1, 0, {'BAD_OWNER': '1'})
    run_loader('not preinit rejected', 1, 0, {'KSU_PREINIT': '0'})
    run_loader('dependency load failure returns to OEM', 1, 2, {'FAIL_LOAD': '2'})
    (modules / 'dep0').mkdir()
    run_loader('already-loaded dependency skipped', 0, 2)
    (modules / 'oplus_bsp_hybridswap_zram').mkdir()
    run_loader('existing OEM provider left alone', 0, 0)
    # Exact retained static ARM64 compiler argv, replacing only input/output
    # and adding the generated header include directory. This is compile-only.
    arm = json.loads((REPO / 'rmx3997/development/installer-ufs-controller-build.json').read_text())
    arm[-3] = str(source)
    arm[-1] = str(out / 'loader-arm64')
    arm[1:1] = ['-I' + str(out)]
    guarded(arm, 'loader-arm64-build')

    spec = importlib.util.spec_from_file_location('provider_test', REPO / 'rmx3997/development/test-provider.py')
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    hybrid = (REPO / 'rmx3997/provider/hybridswap_zram/hybridswap/hybridmain.c').read_text()
    names = ['mem_cgroup_free', 'adjust_alloc_flags', 'mem_cgroup_css_online', 'mem_cgroup_css_offline',
             'alloc_pages_slowpath', 'tune_scan_type', 'shrink_slab_bypass', 'mem_cgroup_id_remove', 'mem_cgroup_alloc']
    preamble = '''#include <assert.h>
#include <stdio.h>
#define CONFIG_HYBRIDSWAP_CORE 1
#define CONFIG_HYBRIDSWAP_SWAPD 1
#define CONFIG_IOMMU_DMA_ALLOC_ADJUST_FLAGS 1
#define log_err(...) ((void)0)
static int active, calls, fail, synced, allocated;
static int reg(int n) { if(++calls==fail)return -5;active|=1<<n;if(n==8)allocated=1;return 0; }
static void unreg(int n) { assert(active&(1<<n));active&=~(1<<n); }
static void tracepoint_synchronize_unregister(void) {synced++;}
'''
    for i, name in enumerate(names):
        preamble += f'static void {name}_hook(void) {{}}\n'
        preamble += f'static int register_trace_android_vh_{name}(void (*f)(void),void *p) {{(void)f;(void)p;return reg({i});}}\n'
        preamble += f'static void unregister_trace_android_vh_{name}(void (*f)(void),void *p) {{(void)f;(void)p;unreg({i});}}\n'
    preamble += '''struct ops {void (*vh_alloc_pages_slowpath)(void),(*vh_tune_scan_type)(void),(*vh_shrink_slab_bypass)(void);};
static struct ops ops={alloc_pages_slowpath_hook,tune_scan_type_hook,shrink_slab_bypass_hook};
static struct ops *hybridswapd_ops=&ops;
'''
    macros = hybrid[hybrid.index('#define REGISTER_HOOK'):hybrid.index('static int register_all_hooks')]
    cases = '''int main(void){for(fail=1;fail<=9;fail++){active=calls=synced=allocated=0;
 assert(register_all_hooks()==-5);assert(!active&&!allocated&&synced==1);}
 fail=0;active=calls=synced=allocated=0;assert(!register_all_hooks());assert(active==511&&allocated);
 unregister_all_hook();assert(!active&&synced==1);puts("PASS all9 hook-registration failure positions and teardown");return 0;}
'''
    hook_source = out / 'hook-unwind.c'
    hook_source.write_text(preamble + macros + helper.function(hybrid, 'register_all_hooks') +
                           helper.function(hybrid, 'unregister_all_hook') + cases)
    guarded(['/usr/bin/clang', '-O1', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
             str(hook_source), '-o', str(out / 'hook-test')], 'hooks-build')
    guarded([str(out / 'hook-test')], 'hooks-run')
    transaction = REPO / 'rmx3997/provider/provider-transaction.sh'
    shell = out / 'transaction-fixture.sh'
    shell.write_text('''. "$1"
events=""
active=0
call() { events="$events $1"; [ "$FAIL" != "$1" ]; }
provider_preflight() { call preflight; }
provider_lock() { call lock; }
provider_unlock() { call unlock; }
provider_stage() { call stage; }
provider_stage_verify() { call verify; }
provider_sync() { sync_count=$((sync_count+1));call "sync$sync_count"; }
provider_discard_stage() { call discard; }
provider_activate() { call activate || return 1;active=1; }
provider_restore() { call restore || return 1;active=0; }
provider_restore_verify() { call restore_verify && [ "$active" = 0 ]; }
provider_boot_transaction() { call boot;return "$BOOT_CODE"; }
provider_install
code=$?
printf '%s|%s|%s\\n' "$code" "$active" "$events"
''')
    transactions = []
    cases = [('success', '', '0', 0, 1), ('firmware reject', 'preflight', '0', 10, 0),
             ('busy lock', 'lock', '0', 10, 0), ('stage error', 'stage', '0', 10, 0),
             ('hash error', 'verify', '0', 10, 0), ('staging sync error', 'sync1', '0', 10, 0),
             ('activation error', 'activate', '0', 10, 0), ('activation sync error', 'sync2', '0', 10, 0),
             ('boot rejected', '', '10', 10, 0), ('boot rollback', '', '70', 70, 0),
             ('unverified boot rollback', '', '71', 71, 0), ('metadata restore failed', 'restore', '70', 71, 1),
             ('metadata restore check failed', 'restore_verify', '70', 71, 0),
             ('metadata restore sync failed', 'sync3', '70', 71, 0)]
    for name, failure, boot, expected, active in cases:
        result = subprocess.run(['/bin/sh', str(shell), str(transaction)], env={**env, 'FAIL': failure,
                                'BOOT_CODE': boot}, capture_output=True, text=True, check=True)
        fields = result.stdout.strip().split('|')
        assert fields[:2] == [str(expected), str(active)], (name, fields, result.stderr)
        transactions.append({'case': name, 'result': expected, 'active_after': active, 'trace': fields[2]})
    (out / 'results.json').write_text(json.dumps({'commands': commands, 'environment': controlled_env,
        'loader_cases': loader_results, 'transaction_cases': transactions,
        'limits': 'Host root-owner/sysfs/finit_module and installer adapters are shims. ARM64 loader compile only, no phone/kernel module loading or actual Android preinit/rollback.'}, indent=2) + '\n')


if __name__ == '__main__':
    main()
