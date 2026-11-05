#!/usr/bin/python3
"""Actual guest rejection + original-byte normal-load fallback, not phone init."""
import importlib.util,json,os,stat,subprocess,shutil,hashlib
from pathlib import Path
REPO=Path(__file__).resolve().parents[2]
R=Path('/home/build/.cache/codex-work/rmx3997-full-features-20261104');P=R/'final-acceptance'
spec=importlib.util.spec_from_file_location('runtime',REPO/'rmx3997/development/run-provider-runtime.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def main():
 run=P/'production-provider-fallback-guest';run.mkdir();env=json.loads((R/'components197/build-environment.json').read_text());records=[]
 def compile(label,cc):
  argv=['/usr/bin/python3',str(REPO/'rmx3997/development/resource-guard.py'),'--log',str(run/(label+'.log')),'--result',str(run/(label+'.json')),'--']+cc
  records.append({'argv':argv,'environment':env,'cwd':str(REPO)});(run/'compile-commands.json').write_text(json.dumps(records,indent=2)+'\n');subprocess.run(argv,env={**os.environ,**env},check=True)
 assets=P/'provider-assets';header=(assets/'provider-inputs.h').read_text();original_hash=m.sha(assets/'original-provider.ko');candidate_hash=m.sha(assets/'provider.ko');assert header.count(candidate_hash)==1
 (run/'provider-inputs.h').write_text(header.replace('./provider.ko','./original-provider.ko').replace(candidate_hash,original_hash))
 cc=json.loads((assets/'loader-command.json').read_text())['argv'];cc=cc[cc.index('--')+1:];cc=[str(run/'fallback-loader') if x==str(assets/'provider-loader') else '-I'+str(run) if x=='-I'+str(assets) else x for x in cc];compile('fallback-loader-build',cc)
 cc=json.loads((R/'provider-phase2/provider-guest-build-command.json').read_text())['argv'];cc=cc[cc.index('--')+1:];cc=[str(REPO/'rmx3997/development/provider-fallback-guest.c') if x==str(REPO/'rmx3997/provider/tests/provider-guest.c') else str(run/'provider-fallback-guest') if x==str(R/'provider-phase2/provider-guest-arm64') else x for x in cc];compile('fallback-consumer-build',cc)
 fixture=run/'fixture';shutil.copytree(P/'production-provider-guest/fixture',fixture)
 (fixture/'FALLBACK_TEST').write_text('candidate hash mismatch then original normal load\n')
 for name in ['fallback-loader','provider-fallback-guest']:shutil.copy2(run/name,fixture/name);(fixture/name).chmod(0o700)
 bad=fixture/'metadata/ksu/preinit/rmx3997-provider/provider.ko';data=bytearray(bad.read_bytes());data[-1]^=1;bad.write_bytes(data)
 disk=run/'disposable-fallback.ext4'
 with disk.open('xb') as f:f.truncate(536870912)
 mkfs=['/usr/bin/mkfs.ext4','-q','-F','-O','^orphan_file','-L','RMXFALLBACK','-d',str(fixture),str(disk)]
 with (run/'mkfs.log').open('wb') as log:subprocess.run(mkfs,stdout=log,stderr=subprocess.STDOUT,check=True)
 commands=[]
 for p in fixture.rglob('*'):
  name='/'+str(p.relative_to(fixture));commands+=['set_inode_field '+name+' uid 0','set_inode_field '+name+' gid 0']
 (run/'owners.debugfs').write_text('\n'.join(commands)+'\n')
 with (run/'owners.log').open('wb') as log:subprocess.run(['/usr/sbin/debugfs','-w','-f',str(run/'owners.debugfs'),str(disk)],stdout=log,stderr=subprocess.STDOUT,check=True)
 entries=m.read_archive(P/'production-feature-guest/initramfs.cpio.gz');entries['metadata']=(stat.S_IFDIR|0o755,b'',0,0)
 for name in ['init','system/bin/init']:entries[name]=(stat.S_IFREG|0o755,(REPO/'rmx3997/development/provider-runtime-init.sh').read_bytes(),0,0)
 prior=P/'production-provider-hybrid-counter-corrected';entries['poweroff-native']=(stat.S_IFREG|0o755,(prior/'poweroff-native').read_bytes(),0,0)
 for guest,info in json.loads((prior/'android-ELF-inputs.json').read_text()).items():entries[guest]=(stat.S_IFREG|0o755,Path(info['path']).read_bytes(),0,0)
 spec=importlib.util.spec_from_file_location('archive',m.OLD/'flashable-ak3-20261104/tests/android-integration/run.py');a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a);a.archive(entries,run/'initramfs.cpio.gz')
 argv=json.loads((P/'production-feature-guest/command.json').read_text())['argv'];argv=argv[argv.index('/usr/bin/qemu-system-aarch64'):];argv[argv.index('-initrd')+1]=str(run/'initramfs.cpio.gz');argv[argv.index('-append')+1]+=' rmx3997.provider_guest=1 rmx3997.fixture_tail=1';argv=[x.replace(str(P/'production-feature-guest/disposable-core.ext4'),str(disk)) for x in argv]
 command=['/usr/bin/python3',str(REPO/'rmx3997/development/resource-guard.py'),'--log',str(run/'console.log'),'--result',str(run/'guard-result.json'),'--','/usr/bin/timeout','--signal=TERM','--kill-after=5s','300s']+argv
 record={'argv':command,'cwd':str(REPO),'environment':env,'Image_sha256':m.sha(R/'components197/out/arch/arm64/boot/Image'),'original_provider_sha256':original_hash,'corrupt_candidate_fixture_sha256':m.sha(bad),'uncorrupted_candidate_sha256':candidate_hash,'mkfs_argv':mkfs,'disk_before_sha256':m.sha(disk),'scope':'Real Baka preinit rejection followed by normal flags0 original-module fallback loader in guest; not execution of untouched Android vendor init_boot','all_acceptance_passed':False};(run/'command.json').write_text(json.dumps(record,indent=2)+'\n');record['exit_code']=subprocess.call(command,env={**os.environ,**env});console=(run/'console.log').read_text(errors='replace');record['observed_markers']=[x for x in console.splitlines() if 'PROVIDER_' in x or 'ksu_preinit:' in x];(run/'results.json').write_text(json.dumps(record,indent=2)+'\n');print('\n'.join(record['observed_markers']))
if __name__=='__main__':main()
