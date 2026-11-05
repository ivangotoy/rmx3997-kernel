#!/usr/bin/python3
"""One disk-backed provider preinit guest using the actual accepted Image.

No kernel build or package acceptance. Preserve each run and report real markers.
"""
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess

REPO = Path(__file__).resolve().parents[2]
TASK = Path('/home/build/.cache/codex-work/rmx3997-full-features-20261104')
ROOT = TASK/'final-acceptance'
OLD = Path('/home/build/Downloads/rea-lk-analysis/rmx3997-custom-gki-build/oem-f2fs-implementation-20261103')


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read_archive(path):
    data=gzip.decompress(path.read_bytes());pos=0;entries={}
    while True:
        assert data[pos:pos+6]==b'070701'
        fields=[int(data[pos+6+i*8:pos+14+i*8],16) for i in range(13)]
        pos+=110;name=data[pos:pos+fields[11]-1].decode();pos=(pos+fields[11]+3)&~3
        body=data[pos:pos+fields[6]];pos=(pos+fields[6]+3)&~3
        if name=='TRAILER!!!':break
        assert fields[2]==fields[3]==0, 'root-owned boot archive required'
        entries[name]=(fields[1],body,fields[9],fields[10])
    return entries


def main():
    run=ROOT/'production-provider-hybrid-counter-corrected';run.mkdir(exist_ok=False)
    stage=TASK/'components197';env=json.loads((stage/'build-environment.json').read_text())
    assert env['TMPDIR']==str(TASK)
    first=ROOT/'production-provider-guest'
    disk=run/'disposable-provider.ext4';shutil.copy2(first/'disposable-provider.ext4',disk)
    # mkfs -d retained host owners: set the fixture's on-disk inode owners
    # offline, before execution. Actual runner/loader ownership checks stay on.
    commands=[]
    fixture=first/'fixture'
    for p in sorted(fixture.rglob('*')):
        guest='/'+str(p.relative_to(fixture))
        commands.extend(['set_inode_field '+guest+' uid 0','set_inode_field '+guest+' gid 0'])
    (run/'root-owner.debugfs').write_text('\n'.join(commands)+'\n')
    ownership=['/usr/sbin/debugfs','-w','-f',str(run/'root-owner.debugfs'),str(disk)]
    with (run/'ownership.log').open('wb') as log:
        subprocess.run(ownership,stdout=log,stderr=subprocess.STDOUT,check=True)
    guest_source=REPO/'rmx3997/provider/tests/provider-guest.c'
    old_command=json.loads((TASK/'provider-phase2/provider-guest-build-command.json').read_text())['argv']
    # Retain the proven static ARM64 consumer compiler flags, unique output.
    cc=old_command[old_command.index('--')+1:] if '--' in old_command else old_command
    cc=[str(run/'provider-guest') if v==str(TASK/'provider-phase2/provider-guest-arm64') else v for v in cc]
    guest_compile=['/usr/bin/python3',str(REPO/'rmx3997/development/resource-guard.py'),
                   '--log',str(run/'consumer-build.log'),'--result',str(run/'consumer-build.json'),'--']+cc
    (run/'consumer-command.json').write_text(json.dumps({'argv':guest_compile,'cwd':str(REPO),'environment':env},indent=2)+'\n')
    prior=ROOT/'production-provider-hybrid-guest'
    shutil.copy2(prior/'provider-guest',run/'provider-guest')
    (run/'consumer-reuse.json').write_text(json.dumps({'prior_command':str(prior/'consumer-command.json'),
        'binary_sha256':sha(run/'provider-guest'),'source_sha256':sha(guest_source),'unchanged_since_prior_compile':True},indent=2)+'\n')
    replace=['/usr/sbin/debugfs','-w','-R','rm /provider-guest',str(disk)]
    write=['/usr/sbin/debugfs','-w','-R','write '+str(run/'provider-guest')+' /provider-guest',str(disk)]
    with (run/'consumer-install.log').open('wb') as log:
        for command in [replace,write]:subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
        for field,value in [('uid','0'),('gid','0'),('mode','0100700')]:
            subprocess.run(['/usr/sbin/debugfs','-w','-R','set_inode_field /provider-guest '+field+' '+value,str(disk)],stdout=log,stderr=subprocess.STDOUT,check=True)
    hybrid_cc=[str(REPO/'rmx3997/development/provider-hybrid-guest.c') if v==str(guest_source) else
               str(run/'provider-hybrid-guest') if v==str(run/'provider-guest') else v for v in cc]+['-pthread']
    hybrid_compile=['/usr/bin/python3',str(REPO/'rmx3997/development/resource-guard.py'),
                    '--log',str(run/'hybrid-build.log'),'--result',str(run/'hybrid-build.json'),'--']+hybrid_cc
    (run/'hybrid-command.json').write_text(json.dumps({'argv':hybrid_compile,'cwd':str(REPO),'environment':env},indent=2)+'\n')
    subprocess.run(hybrid_compile,env={**os.environ,**env},check=True)
    with (run/'hybrid-install.log').open('wb') as log:
        for request in ['write '+str(run/'provider-hybrid-guest')+' /provider-hybrid-guest',
                        'set_inode_field /provider-hybrid-guest uid 0','set_inode_field /provider-hybrid-guest gid 0',
                        'set_inode_field /provider-hybrid-guest mode 0100700']:
            subprocess.run(['/usr/sbin/debugfs','-w','-R',request,str(disk)],stdout=log,stderr=subprocess.STDOUT,check=True)
    entries=read_archive(ROOT/'production-feature-guest/initramfs.cpio.gz')
    # Same real NDK/static ARM64 compiler invocation as retained feature init;
    # only the guest-only shutdown source/output changes.
    oldrun=Path('/home/build/.cache/codex-work/rmx3997-feature-parity/feature-runtime-20261104T154656.551569Z')
    cc=json.loads((oldrun/'inputs.json').read_text())['controller_build_argv']
    cc=[str(REPO/'rmx3997/development/provider-runtime-poweroff.c') if v==str(REPO/'rmx3997/development/feature-runtime.c') else
        str(run/'poweroff-native') if v==str(oldrun/'init') else v for v in cc]
    compile_argv=['/usr/bin/python3',str(REPO/'rmx3997/development/resource-guard.py'),
                  '--log',str(run/'poweroff-build.log'),'--result',str(run/'poweroff-build.json'),'--']+cc
    (run/'poweroff-command.json').write_text(json.dumps({'argv':compile_argv,'cwd':str(REPO),'environment':env},indent=2)+'\n')
    shutil.copy2(prior/'poweroff-native',run/'poweroff-native')
    (run/'poweroff-reuse.json').write_text(json.dumps({'prior_command':str(prior/'poweroff-command.json'),
        'binary_sha256':sha(run/'poweroff-native'),'source_sha256':sha(REPO/'rmx3997/development/provider-runtime-poweroff.c'),
        'unchanged_since_prior_compile':True},indent=2)+'\n')
    entries['poweroff-native']=(stat.S_IFREG|0o755,(run/'poweroff-native').read_bytes(),0,0)
    entries['metadata']=(stat.S_IFDIR|0o755,b'',0,0)
    source=REPO/'rmx3997/development/provider-runtime-init.sh'
    for name in ['init','system/bin/init']:
        entries[name]=(stat.S_IFREG|0o755,source.read_bytes(),0,0)
    normal=OLD/'flashable-ak3-20261104/firmware-identity/normal-system-tools'
    todo=[normal/'toybox',normal/'linker64'];libs={}
    while todo:
        src=todo.pop();guest='system/bin/'+src.name if src.parent==normal else 'system/lib64/'+src.name
        if guest in libs:continue
        entries[guest]=(stat.S_IFREG|0o755,src.read_bytes(),0,0)
        libs[guest]={'path':str(src),'sha256':sha(src)}
        elf=subprocess.check_output(['readelf','-d',str(src)],text=True)
        todo += [normal/'linker64' if n=='ld-android.so' else normal/'lib64'/n
                 for n in re.findall(r'Shared library: \[(.*?)\]',elf)]
    (run/'android-ELF-inputs.json').write_text(json.dumps(libs,indent=2)+'\n')
    spec=importlib.util.spec_from_file_location('archive',OLD/'flashable-ak3-20261104/tests/android-integration/run.py')
    native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)
    native.archive(entries,run/'initramfs.cpio.gz')
    base=json.loads((ROOT/'production-feature-guest/command.json').read_text())['argv']
    argv=base[base.index('/usr/bin/qemu-system-aarch64'):]
    argv[argv.index('-initrd')+1]=str(run/'initramfs.cpio.gz')
    argv[argv.index('-append')+1]+=' rmx3997.provider_guest=1 rmx3997.fixture_tail=1'
    argv=[v.replace(str(ROOT/'production-feature-guest/disposable-core.ext4'),str(disk)) for v in argv]
    backing=run/'disposable-hybrid.raw'
    with backing.open('xb') as f:f.truncate(268435456)
    argv += ['-drive','file='+str(backing)+',if=none,format=raw,id=hybrid',
             '-device','ufs-lu,drive=hybrid,lun=1']
    command=['/usr/bin/python3',str(REPO/'rmx3997/development/resource-guard.py'),
             '--log',str(run/'console.log'),'--result',str(run/'guard-result.json'),'--',
             '/usr/bin/timeout','--signal=TERM','--kill-after=5s','300s']+argv
    record={'argv':command,'cwd':str(REPO),'environment':env,
            'Image_sha256':sha(stage/'out/arch/arm64/boot/Image'),
            'controller_sha256':sha(source),'producer_sha256':sha(Path(__file__)),
            'ownership_argv':ownership,'initramfs_sha256':sha(run/'initramfs.cpio.gz'),
            'provider_assets_manifest':str(ROOT/'provider-assets/manifest.json'),
            'disk_before_sha256':sha(disk),'phone_writes':False}
    (run/'command.json').write_text(json.dumps(record,indent=2)+'\n')
    record['exit_code']=subprocess.call(command,env={**os.environ,**env})
    console=(run/'console.log').read_text(errors='replace')
    record['observed_markers']=[v for v in console.splitlines() if any(n in v for n in
        ['PROVIDER_','RMX provider','ksu_preinit','Unknown symbol','disagrees about','invalid module'])]
    record['disk_after_sha256']=sha(disk)
    record['all_acceptance_passed']=False
    (run/'results.json').write_text(json.dumps(record,indent=2)+'\n')
    print('\n'.join(record['observed_markers']))


if __name__=='__main__':main()
