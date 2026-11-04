#!/usr/bin/python3
"""Reuse the proven four-job build/ABI environment without changing its inputs."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

repo = Path(__file__).resolve().parents[2]
old = Path('/home/build/Downloads/rea-lk-analysis/rmx3997-custom-gki-build/oem-f2fs-implementation-20261103')
stage = Path('/home/build/.cache/codex-work/rmx3997-feature-parity') / sys.argv[1]
stage.mkdir(parents=True, exist_ok=False)
for d in ('kernel', 'out', 'abi', 'tests'):
    (stage / d).mkdir()
(stage / 'kernel/common').symlink_to(repo)
(stage / 'kernel/build').symlink_to(old / 'kernel/build')
(stage / 'kernel/prebuilts').symlink_to(old / 'kernel/prebuilts')
for name in ('resource_guard.py', 'run_build.py', 'run_abi_checks.py', 'run_binary_checks.py',
             'verify_binary.py', 'verify_btf.py', 'abi-targets.json', 'tests/check_f2fs_btf.py',
             'abi/abi_symbollist', 'abi/abi_symbollist.report'):
    shutil.copy2(old / name, stage / name)
env = json.loads((repo / 'rmx3997/build-environment.json').read_text())
env['TMPDIR'] = str(stage / 'scratch')
env['PYTHONPYCACHEPREFIX'] = str(stage / 'pycache')
env['PYTHONDONTWRITEBYTECODE'] = '1'
(stage / 'scratch').mkdir()
(stage / 'build-environment.json').write_text(json.dumps(env, indent=2) + '\n')
argv = json.loads((repo / 'rmx3997/build-argv.json').read_text())
argv[2] = str(repo)
argv[3] = 'O=' + str(stage / 'out')
(stage / 'build-argv.json').write_text(json.dumps(argv, indent=2) + '\n')
shutil.copy2(repo / 'rmx3997/config/abi-symbol-list.txt', stage / 'out/abi_symbollist.raw')
config = (repo / 'rmx3997/development/bakasu-susfs.config').read_text()
config = '\n'.join('CONFIG_UNUSED_KSYMS_WHITELIST="' + str(stage / 'out/abi_symbollist.raw') + '"'
                   if s.startswith('CONFIG_UNUSED_KSYMS_WHITELIST=') else s for s in config.splitlines()) + '\n'
(stage / 'out/.config').write_text(config)
runenv = os.environ.copy()
runenv.update(env)
with (stage / 'prepare.log').open('wb') as log:
    # olddefconfig must resolve the hook choice before the driver Kbuild is parsed.
    for targets in (['olddefconfig'], ['headers_install'], ['prepare', 'scripts'], ['init/'], ['security/selinux/'],
                    ['drivers/kernelsu/', 'fs/susfs.o']):
        command = argv[:-2] + targets
        log.write(('COMMAND ' + repr(command) + '\n').encode()); log.flush()
        code = subprocess.call(command, env=runenv, stdout=log, stderr=subprocess.STDOUT)
        print(' '.join(targets), code, flush=True)
        if code:
            sys.exit(code)
print(stage)
