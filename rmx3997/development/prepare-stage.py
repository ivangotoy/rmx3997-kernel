#!/usr/bin/python3
"""Prepare the current production config with relocated retained build prerequisites."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

repo = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--ancestor', type=Path, required=True,
                    help='Retained OEM-F2FS build workspace with kernel/build and kernel/prebuilts')
parser.add_argument('--stage', type=Path, required=True, help='New disk-backed output directory')
parser.add_argument('--config-only', action='store_true', help='Stop after whitelist binding and olddefconfig')
args = parser.parse_args()
old = args.ancestor.resolve(strict=True)
stage = args.stage.resolve()
stage.mkdir(parents=True, exist_ok=False)
for d in ('kernel', 'out', 'abi', 'tests'):
    (stage / d).mkdir()
(stage / 'kernel/common').symlink_to(repo)
(stage / 'kernel/build').symlink_to(old / 'kernel/build')
(stage / 'kernel/prebuilts').symlink_to(old / 'kernel/prebuilts')
for name in ('run_build.py', 'run_abi_checks.py', 'run_binary_checks.py',
             'verify_binary.py', 'verify_btf.py', 'abi-targets.json', 'tests/check_f2fs_btf.py',
             'abi/abi_symbollist', 'abi/abi_symbollist.report'):
    shutil.copy2(old / name, stage / name)
# Never regenerate the retired ancestor guard. Stage both canonical policy and CLI adapter.
for name in ('resource_guard.py', 'resource-guard.py'):
    shutil.copy2(repo / 'rmx3997/development' / name, stage / name)
# Ancestor launchers use the legacy CLI; rewrite only their guard pathname.
for name in ('run_build.py', 'run_abi_checks.py'):
    launcher = stage / name
    launcher.write_text(launcher.read_text().replace("'resource_guard.py'", "'resource-guard.py'"))
# The JSON files are historical invocation templates. Relocate the retained
# prerequisite workspace without changing flags, compiler version or build identity.
template = json.loads((repo / 'rmx3997/build-argv.json').read_text())
original = str(Path(template[2]).parents[2])
prebuilts = str((old / 'kernel/prebuilts').resolve(strict=True))
original_prebuilts = str(Path(original) / 'kernel/prebuilts')
def relocate(value):
    return value.replace(original_prebuilts, prebuilts)
env = {k: relocate(v) for k, v in
       json.loads((repo / 'rmx3997/build-environment.json').read_text()).items()}
env['TMPDIR'] = str(stage / 'scratch')
env['PYTHONPYCACHEPREFIX'] = str(stage / 'pycache')
env['PYTHONDONTWRITEBYTECODE'] = '1'
(stage / 'scratch').mkdir()
(stage / 'build-environment.json').write_text(json.dumps(env, indent=2) + '\n')
argv = [relocate(v) for v in template]
argv[2] = str(repo)
argv[3] = 'O=' + str(stage / 'out')
(stage / 'build-argv.json').write_text(json.dumps(argv, indent=2) + '\n')
# Bind the current canonical whitelist instead of retaining a copied ancestor
# path. Use the same helper when preparing an already-existing feature stage.
(stage / 'out/.config').write_text((repo / 'rmx3997/config/production.config').read_text())
subprocess.run([sys.executable, str(repo / 'rmx3997/development/prepare-kmi-whitelist.py'),
                '--stage', str(stage), '--evidence', str(stage / 'whitelist-preparation')], check=True)
runenv = os.environ.copy()
runenv.update(env)
with (stage / 'prepare.log').open('wb') as log:
    # olddefconfig must resolve the hook choice before the driver Kbuild is parsed.
    targets_to_run = [['olddefconfig']]
    if not args.config_only:
        targets_to_run += [['headers_install'], ['prepare', 'scripts'], ['init/'],
                           ['security/selinux/'], ['drivers/kernelsu/', 'fs/susfs.o']]
    for targets in targets_to_run:
        command = argv[:-2] + targets
        log.write(('COMMAND ' + repr(command) + '\n').encode()); log.flush()
        code = subprocess.call(command, env=runenv, stdout=log, stderr=subprocess.STDOUT)
        print(' '.join(targets), code, flush=True)
        if code:
            sys.exit(code)
print(stage)
