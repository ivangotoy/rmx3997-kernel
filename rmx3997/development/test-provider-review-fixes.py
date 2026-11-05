#!/usr/bin/python3
"""Focused four-finding regressions; host shims are not kernel/phone proof."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[2]
TASK = Path('/home/build/.cache/codex-work/rmx3997-full-features-20261104')


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def signal_cases(out):
    """Actual core/provider shells, POSIX signals, 4KiB disk-file adapters."""
    packer = load(REPO / 'rmx3997/development/package-provider-candidate.py', 'provider_packer')
    original = (REPO / 'rmx3997/development/installer-core-checkpoint/installer-core.sh').read_text()
    core = packer.provider_core_script(original)
    # Complete-template guard rejects drift in every terminal/handler block.
    for old, new in [('    WRITE_STARTED=0\n    installer_log "INSTALL VERIFIED:',
                      '    WRITE_STARTED=0\n    : changed\n    installer_log "INSTALL VERIFIED:'),
                     ('installer_interrupt() {', 'installer_interrupt() {\n    : changed'),
                     ('    return 0\n}', '    return 0 # changed\n}')]:
        assert old in original
        try:
            packer.provider_core_script(original.replace(old, new, 1))
        except ValueError:
            pass
        else:
            raise AssertionError('changed core template accepted')

    def checkpoint(text, old, phase, after=False):
        assert text.count(old) == 1, (phase, text.count(old))
        insertion = '    pause_at ' + phase + '\n'
        return text.replace(old, old + insertion if after else insertion + old, 1)

    # Pauses only: production operations and installed traps remain unchanged.
    core = checkpoint(core, "installer_unlock() {\n", 'core_unlock_before_mask', True)
    core = checkpoint(core, '    return "$unlock_result"\n', 'core_unlock_after_rearm')
    core = checkpoint(core, '    installer_unlock\n    return 0\n', 'core_return', True)
    # The preceding insertion follows return and would be unreachable; move it
    # immediately before return while retaining the exact real unlock sequence.
    core = core.replace('    installer_unlock\n    return 0\n    pause_at core_return\n',
                        '    installer_unlock\n    pause_at core_return\n    return 0\n')
    core = core.replace("installer_interrupt() {\n    trap '' INT TERM HUP\n",
                        "installer_interrupt() {\n    trap '' INT TERM HUP\n    repeat_gate\n", 1)
    provider = (REPO / 'rmx3997/provider/provider-transaction.sh').read_text()
    for old, phase, after in [
        ("    trap '' INT TERM HUP\n    PROVIDER_COMMITTED=1\n", 'commit_before_mask', False),
        ('    PROVIDER_COMMITTED=1\n', 'commit_before_flag', False),
        ('    PROVIDER_COMMITTED=1\n', 'commit_after_flag', True),
        ('    WRITE_STARTED=0\n', 'commit_after_clear', True),
        ('        trap installer_interrupt INT TERM HUP\n', 'commit_after_rearm', True),
        ('    provider_boot_transaction\n', 'provider_core_return', True),
        ('    PROVIDER_RESULT=$result\n    provider_finish || return 71\n', 'provider_before_finish', True),
        ('provider_finish() {\n', 'provider_finish_before_mask', True),
        ('    trap provider_interrupt INT TERM HUP\n    return "$result"\n', 'provider_finish_rearm', False),
        ('    trap provider_interrupt INT TERM HUP\n    return "$result"\n', 'provider_finish_return', True),
    ]:
        provider = checkpoint(provider, old, phase, after)
    provider = provider.replace('    PROVIDER_RESULT=$result\n    provider_finish || return 71\n    pause_at provider_before_finish\n',
                                '    PROVIDER_RESULT=$result\n    pause_at provider_before_finish\n    provider_finish || return 71\n')
    provider = provider.replace('    trap provider_interrupt INT TERM HUP\n    return "$result"\n    pause_at provider_finish_return\n',
                                '    trap provider_interrupt INT TERM HUP\n    pause_at provider_finish_return\n    return "$result"\n')
    provider = provider.replace("provider_interrupt() {\n    trap '' INT TERM HUP\n",
                                "provider_interrupt() {\n    trap '' INT TERM HUP\n    repeat_gate\n", 1)
    (out / 'fixture-provider.sh').write_text(provider)
    payload, stock, init = b'B' * 4096, b'A' * 4096, b'C' * 4096
    for key, data in [('EXPECTED_PAYLOAD', payload), ('EXPECTED_STOCK', stock), ('EXPECTED_INIT_BOOT', init)]:
        import re
        core, count = re.subn('(?m)^' + key + '=[0-9a-f]{64}$',
                              key + '=' + hashlib.sha256(data).hexdigest(), core)
        assert count == 1
    core = core.replace('BOOT_BYTES=67108864\n', 'BOOT_BYTES=4096\n').replace('INIT_BOOT_BYTES=8388608\n', 'INIT_BOOT_BYTES=4096\n')
    (out / 'fixture-core.sh').write_text(core)
    adapter = out / 'signal-adapter.sh'
    adapter.write_text('''RUN=$1
PHASE=$2
. "$3"
. "$4"
pause_at() {
 local pause_status=$?
 if [ "$PHASE" = "$1" ];then
  printf '%s\\n' "$1" > "$RUN/ready"
  while [ ! -e "$RUN/go" ];do /usr/bin/sleep 0.01;done
 fi
 return "$pause_status"
}
repeat_gate() {
 if [ "${REPEAT:-0}" = 1 ] && [ -e "$RUN/signal.sent" ] && [ ! -e "$RUN/repeat.done" ];then
  touch "$RUN/repeat.done" "$RUN/repeat.ready"
  while [ ! -e "$RUN/repeat.go" ];do /usr/bin/sleep 0.01;done
 fi
}
platform_log() {
 printf '%s\\n' "$*"
 case $* in
 'INSTALL VERIFIED:'*) pause_at install_log1;;
 'Rollback preserved at '*) pause_at install_log2;;
 esac
 [ "${FAIL_LOG:-0}" != 1 ]
}
platform_uid() { echo 0; }
platform_prop() {
 case $1 in
 ro.build.version.sdk) echo 36;;ro.product.oplus_model) echo RMX3997GL;;
 ro.build.display.id) echo 'RMX3997_16.0.5.1300(EX01)';;
 ro.build.version.ota) echo RMX3997_11.F.81_2810_202610091732;;ro.boot.slot_suffix) echo _b;;esac
}
platform_release() { echo 5.15.197-android13-8-fixture; }
platform_slot_evidence() { echo _b; }
platform_workspace_safe() { [ "$1" = "$RUN/work" ]; }
platform_partition() { case $1 in boot_b) echo "$RUN/boot";;init_boot_b) echo "$RUN/init";;*)return 1;;esac; }
platform_size() { /usr/bin/stat -c %s "$1"; }
platform_hash() { /usr/bin/sha256sum "$1" | /usr/bin/cut -d ' ' -f 1; }
platform_free_bytes() { echo 1073741824; }
platform_lock() { mkdir "$RUN/core.lock" || return 1;pause_at corelock; }
platform_unlock() { pause_at core_unlock; rmdir "$RUN/core.lock"; [ "${FAIL_CORE_UNLOCK:-0}" != 1 ]; }
platform_backup() { cp "$1" "$2" || return 1;pause_at backup; }
platform_sync() { :; }
platform_write() {
 if [ "$1" = "$PAYLOAD" ];then
  /usr/bin/head -c 1024 "$1" > "$2" || return 1
  pause_at write
  cp "$1" "$2"
 else
  [ "${FAIL_RESTORE:-0}" != 1 ] || return 1
  RESTORING=1
  cp "$1" "$2"
 fi
}
platform_readback() {
 pause_at readback;cp "$1" "$2" || return 1
 if [ "${FAIL_READBACK:-0}" = 1 ] && [ "${RESTORING:-0}" != 1 ];then return 1;fi
}
provider_preflight() { :; }
provider_lock() { mkdir "$RUN/provider.lock" || return 1;pause_at providerlock; }
provider_unlock() { pause_at provider_unlock;repeat_gate;rmdir "$RUN/provider.lock"; [ "${FAIL_PROVIDER_UNLOCK:-0}" != 1 ]; }
provider_stage() { mkdir "$RUN/staged"; }
provider_stage_verify() { [ -d "$RUN/staged" ]; }
provider_sync() { :; }
provider_discard_stage() { :; }
provider_activate() { mv "$RUN/staged" "$RUN/active" || return 1;pause_at activate; }
provider_restore() {
 [ "${FAIL_METADATA:-0}" != 1 ] || return 1
 if [ -d "$RUN/active" ];then mv "$RUN/active" "$RUN/staged";fi
}
provider_restore_verify() { [ ! -e "$RUN/active" ]; }
provider_boot_transaction() { installer_main "$PAYLOAD" "$WORKDIR"; }
PAYLOAD=$RUN/payload
WORKDIR=$RUN/work
provider_install
status=$?
pause_at provider_install_return
exit "$status"
''')
    rows = []
    precommit = ['providerlock', 'activate', 'corelock', 'backup', 'write', 'readback', 'commit_before_mask']
    committed = ['commit_before_flag', 'commit_after_flag', 'commit_after_clear', 'commit_after_rearm',
                 'install_log1', 'install_log2', 'core_unlock_before_mask', 'core_unlock',
                 'core_unlock_after_rearm', 'core_return', 'provider_core_return', 'provider_before_finish',
                 'provider_finish_before_mask', 'provider_unlock', 'provider_finish_rearm',
                 'provider_finish_return', 'provider_install_return']
    cases = [(phase, sig, {'REPEAT': '1'},
              0 if phase in committed else 70 if phase in ('write', 'readback', 'commit_before_mask') else 10,
              phase in committed)
             for phase in precommit + committed for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)]
    cases += [('none', None, {}, 0, True),
              ('write', signal.SIGTERM, {'FAIL_RESTORE': '1', 'REPEAT': '1'}, 71, False),
              ('write', signal.SIGTERM, {'FAIL_METADATA': '1', 'REPEAT': '1'}, 71, False),
              ('none', None, {'FAIL_READBACK': '1'}, 70, False),
              ('none', None, {'FAIL_CORE_UNLOCK': '1'}, 71, True),
              ('none', None, {'FAIL_PROVIDER_UNLOCK': '1'}, 71, True),
              ('install_log1', signal.SIGTERM, {'FAIL_LOG': '1', 'REPEAT': '1'}, 0, True),
              ('provider_install_return', signal.SIGHUP, {'FAIL_CORE_UNLOCK': '1', 'REPEAT': '1'}, 71, True),
              ('provider_install_return', signal.SIGINT, {'FAIL_PROVIDER_UNLOCK': '1', 'REPEAT': '1'}, 71, True),
              ('provider_install_return', signal.SIGTERM, {'FAIL_READBACK': '1', 'REPEAT': '1'}, 70, False)]
    for index, (phase, sig, extra, expected, is_committed) in enumerate(cases):
        if index < int(os.environ.get("PROVIDER_SIGNAL_START", "0")): continue
        run = out / str(index)
        run.mkdir(); (run / 'work').mkdir()
        for name, data in [('payload', payload), ('boot', stock), ('init', init)]: (run / name).write_bytes(data)
        argv = ['/bin/sh', str(adapter), str(run), phase, str(out / 'fixture-core.sh'),
                str(out / 'fixture-provider.sh')]
        with (run / 'log').open('wb') as log:
            proc = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, env={**os.environ, **extra})
            try:
                if sig is not None:
                    deadline = time.monotonic() + 5
                    while not (run / 'ready').exists():
                        if proc.poll() is not None or time.monotonic() > deadline:
                            raise AssertionError(('fixture did not reach phase', phase, proc.poll(), (run / 'log').read_text()))
                        time.sleep(0.005)
                    (run / 'signal.sent').touch()
                    os.kill(proc.pid, sig)
                    if extra.get('REPEAT'):
                        # A masked target remains at the primary pause. An active
                        # handler masks reentry and waits at repeat_gate instead.
                        # Neither can exit before we release both barriers.
                        time.sleep(0.03)
                        for again in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                            os.kill(proc.pid, again)
                            time.sleep(0.002)
                        (run / 'repeat.go').touch()
                    (run / 'go').touch()
                code = proc.wait(timeout=5)
            finally:
                if proc.poll() is None: proc.kill(); proc.wait()
        boot_hash = hashlib.sha256((run / 'boot').read_bytes()).hexdigest()
        assert code == expected, (phase, sig, code, expected, (run / 'log').read_text())
        assert not (run / 'core.lock').exists() and not (run / 'provider.lock').exists(), (phase, sig, 'lock remains')
        assert (run / 'init').read_bytes() == init
        if not extra.get('FAIL_RESTORE'):
            assert (run / 'boot').read_bytes() == (payload if is_committed else stock)
        assert (run / 'active').exists() == bool(is_committed or extra.get('FAIL_METADATA'))
        rows.append({'phase': phase, 'signal': sig.name if sig else None, 'exit_code': code,
                     'boot_sha256': boot_hash, 'locks_removed': True, 'faults': extra,
                     'committed_pair': is_committed, 'additional_real_signals': 3 if extra.get('REPEAT') else 0,
                     'argv': argv, 'log': str(run / 'log')})
        (out / 'results.partial.json').write_text(json.dumps(rows, indent=2) + '\n')
    (out / 'results.json').write_text(json.dumps({'cases': rows, 'limits':
        'Actual signals/traps across actual coordinated core/provider bodies; 4KiB regular-file platform adapters. Not64MiB Android/native/phone proof.'}, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--signal-start', type=int, default=0, help='Resume only unvalidated cases; retain earlier case evidence')
    parser.add_argument('--only', choices=['init', 'nomount', 'signals', 'all'], default='all')
    args = parser.parse_args()
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=False)
    env = json.loads((TASK / 'components197/build-environment.json').read_text())
    env['PROVIDER_SIGNAL_START'] = str(args.signal_start)
    helper = load(REPO / 'rmx3997/development/test-provider.py', 'provider_body')
    results = []

    def run(argv, label):
        command = ['/usr/bin/python3', str(REPO / 'rmx3997/development/resource-guard.py'),
                   '--log', str(out / (label + '.log')), '--result', str(out / (label + '.json')), '--'] + argv
        result = subprocess.run(command, env={**os.environ, **env})
        results.append({'argv': command, 'cwd': str(REPO), 'exit_code': result.returncode})
        return result.returncode

    try:
        for kind in ('init', 'nomount'):
            if args.only not in (kind, 'all'): continue
            fixture = (REPO / f'rmx3997/provider/tests/review-{kind}.h').read_text()
            preamble, cases = fixture.split('/* CASES */')
            if kind == 'init':
                drv = (REPO / 'rmx3997/provider/hybridswap_zram/zram_drv.c').read_text()
                hybrid = (REPO / 'rmx3997/provider/hybridswap_zram/hybridswap/hybridmain.c').read_text()
                bodies = helper.function(hybrid, 'hybridswap_pre_init')
                bodies += ''.join(helper.function(drv, name) for name in ('zram_add', 'destroy_devices', 'zram_init'))
            else:
                src = (REPO / 'fs/nomount/nomount.c').read_text()
                bodies = helper.function((REPO / 'fs/dcache.c').read_text(), 'd_set_d_op')
                bodies += ''.join(helper.function(src, name) for name in ('nm_super_record', 'nm_restore_sop_if_drained',
                    'nm_clear_dops_sb', 'nm_restore_superblocks', 'nm_materialize_rule', 'nm_hijacked_drop_inode',
                    'nm_hijacked_evict_inode', 'nm_shutdown_release', 'nm_reboot_notify'))
                assert 'atomic_inc(&record->virtual_inodes)' in helper.function(src, 'nm_init_prealloc_inode')
                assert 'READ_ONCE(nm_shutdown_released)' in helper.function(src, 'nm_hijack_superblock')
                assert 'READ_ONCE(nm_shutdown_released)' in helper.function(src, 'nm_hijack_dentry_ops')
            source = out / (kind + '.c'); source.write_text(preamble + bodies + cases)
            compiler = ['/usr/bin/clang', '-D_GNU_SOURCE', '-O1', '-g', '-pthread', '-fsanitize=address,undefined',
                        '-fno-sanitize-recover=all', str(source), '-o', str(out / kind)]
            if run(compiler, kind + '-build'): return 1
            if run([str(out / kind)], kind + '-run'): return 1
        if args.only in ('signals', 'all'):
            if run(['/usr/bin/python3', str(Path(__file__).resolve()), '--signal-worker', str(out / 'signals')], 'signals-run'):
                return 1
        return 0
    finally:
        (out / 'execution-index.json').write_text(json.dumps({'commands': results, 'environment': env,
            'limits': 'Focused host resource/VFS/SRCU/platform shims, plus actual OS signals; no new Image or kernel/phone runtime.'}, indent=2) + '\n')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--signal-worker':
        target = Path(sys.argv[2]); target.mkdir(); signal_cases(target)
    else:
        raise SystemExit(main())
