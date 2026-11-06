#!/usr/bin/env python3
"""One actual packaged installer execution in the retained disposable ARM64 VM."""
import argparse, datetime, gzip, hashlib, json, os, pathlib, re, shutil, stat, subprocess, sys, time, zipfile
R=pathlib.Path(__file__).resolve().parent; P=R.parent.parent; N=P.parent
Q=N/'qemu-guest-boot-20261103'
FW=pathlib.Path('/home/build/Downloads/rea-lk-analysis/oem-module-compatibility-20261103/vendor_boot_b/files/system')
NORMAL=P/'firmware-identity/normal-system-tools'
STOCK=pathlib.Path('/home/build/Downloads/RMX3997_custom_boot_b_WORKING.img')
INIT=pathlib.Path('/mnt/Users/ivan/Pictures/REALME/oplus_ossi_16_1791533415164_2611033311/init_boot_b.img')
EXPECTED_STOCK='64da6e27c094fd43afe33a345fd53b023f5201c1150d2a1b1e8ff0428cf48881'
EXPECTED_INIT='22f6caff3b744be48c937825aae8f4392d43a14921a5d3bbc673aba8d22deee9'
EXPECTED_PAYLOAD='be567b3f6c0f2e343a808d9c2617f6aef75a6695670d44c65fc56f80014b8326'
def digest(path):
 h=hashlib.sha256()
 with pathlib.Path(path).open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()
def runlog(argv, log):
 with log.open('xb') as f:subprocess.run(argv,stdout=f,stderr=subprocess.STDOUT,check=True)
def archive(entries,path):
 out=bytearray();ino=1
 def add(name,data,mode,maj=0,minr=0):
  nonlocal ino
  name=name.encode()+b'\0';fields=[ino,mode,0,0,1,0,len(data),0,0,maj,minr,len(name),0];ino+=1
  out.extend(b'070701'+b''.join(f'{v:08x}'.encode() for v in fields));out.extend(name)
  out.extend(bytes((-len(out))%4));out.extend(data);out.extend(bytes((-len(out))%4))
 for name,(mode,data,ma,mi) in entries.items():add(name,data,mode,ma,mi)
 add('TRAILER!!!',b'',0);path.write_bytes(gzip.compress(bytes(out),mtime=0))
def main():
 a=argparse.ArgumentParser();a.add_argument('--zip',type=pathlib.Path,required=True);a.add_argument('--rollback-write-error',action='store_true');o=a.parse_args();package=o.zip.resolve()
 assert digest(STOCK)==EXPECTED_STOCK and digest(INIT)==EXPECTED_INIT
 assert (R/'init').is_file(),'Compile only changed static guest init first'
 assert shutil.which('qemu-system-aarch64') and shutil.which('mkfs.ext4') and shutil.which('debugfs')
 run=R/('run-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'));run.mkdir()
 (R/'latest-run.txt').write_text(str(run)+'\n')
 with zipfile.ZipFile(package) as z:
  entry=z.read('META-INF/com/google/android/update-binary');busybox=z.read('tools/busybox')
  assert hashlib.sha256(z.read('boot.img')).hexdigest()==EXPECTED_PAYLOAD
  assert hashlib.sha256(busybox).hexdigest()=='c629fce4b0dd3ba9775f851d0941e74582115f423258d3a79800f2bd11d30f5c'
 # Actual shipping ELF dependency closure, resolved before VM execution.
 libraries={}; todo=[NORMAL/'toybox',NORMAL/'ziptool',NORMAL/'linker64']
 while todo:
  src=todo.pop()
  guest='/system/bin/'+src.name if src.parent==NORMAL else '/system/lib64/'+src.name
  if guest in libraries:continue
  assert src.is_file(),src
  elf=subprocess.check_output(['readelf','-l','-d',str(src)],text=True)
  deps=re.findall(r'Shared library: \[(.*?)\]',elf)
  libraries[guest]={'source':str(src),'sha256':digest(src),'needed':deps}
  todo += [NORMAL/'linker64' if d=='ld-android.so' else NORMAL/'lib64'/d for d in deps]
 (run/'android-elf-inputs.json').write_text(json.dumps(libraries,indent=2)+'\n')
 # Cheap loader acceptance: all non-weak imported dynamic symbols must have a
 # provider in the actual chosen binary closure, before spending a guest run.
 defined=set();undefined={}
 for guest,info in libraries.items():
  table=subprocess.check_output(['readelf','--dyn-syms','--wide',info['source']],text=True)
  required=set()
  for line in table.splitlines():
   parsed=re.match(r'^\s*\d+:\s+\S+\s+\d+\s+.+?\s+(GLOBAL|WEAK|LOCAL)\s+\S+\s+(\S+)\s+(\S+)',line)
   if not parsed:continue
   binding,index,symbol=parsed.groups();symbol=symbol.split('@')[0]
   if index=='UND' and binding!='WEAK':required.add(symbol)
   elif index!='UND':defined.add(symbol)
  undefined[guest]=required
 unresolved={guest:sorted(names-defined) for guest,names in undefined.items() if names-defined}
 (run/'loader-symbol-preflight.json').write_text(json.dumps({'status':'PASS' if not unresolved else 'BLOCKED','unresolved_strong_symbols':unresolved},indent=2)+'\n')
 assert not unresolved,unresolved
 entries={}
 def directory(name):entries[name]=(stat.S_IFDIR|0o755,b'',0,0)
 def file(name,data,mode=0o755):entries[name]=(stat.S_IFREG|mode,data,0,0)
 def link(name,dest):entries[name]=(stat.S_IFLNK|0o777,dest.encode(),0,0)
 for d in ('dev','dev/block','dev/block/by-name','proc','sys','data','system','system/bin','system/lib64','system/xbin','vendor','vendor/bin'):directory(d)
 entries['dev/console']=(stat.S_IFCHR|0o600,b'',5,1);entries['dev/null']=(stat.S_IFCHR|0o666,b'',1,3)
 file('init',(R/'init').read_bytes());file('busybox',busybox);file('entry',entry);file('package.zip',package.read_bytes(),0o600)
 for guest,info in libraries.items():file(guest.lstrip('/'),pathlib.Path(info['source']).read_bytes())
 link('system/bin/unzip','ziptool')
 link('system/bin/sh','/busybox')
 for tool in ('id','mkdir','chmod'):link('system/bin/'+tool,'toybox')
 file('system/bin/getprop',b'''#!/system/bin/sh
case "$1" in
ro.product.oplus_model) echo RMX3997GL;;
ro.build.version.sdk) echo 36;;
ro.build.display.id) echo 'RMX3997_16.0.5.1300(EX01)';;
ro.build.version.ota) echo RMX3997_11.F.81_2810_202610091732;;
ro.boot.slot_suffix) echo _b;;
sys.boot_completed) echo 1;;
*) exit 1;;
esac
''')
 archive(entries,run/'initramfs.cpio.gz')
 shutil.copyfile(STOCK,run/'boot.raw');shutil.copyfile(INIT,run/'init.raw')
 with (run/'data.ext4').open('xb') as f:f.truncate(536870912)
 fmt=['/usr/bin/mkfs.ext4','-q','-F','-O','^orphan_file','-L','RMX_AK3_DISPOSABLE',str(run/'data.ext4')]
 runlog(fmt,run/'mkfs-ext4.log')
 argv=json.loads((Q/'qemu-argv.json').read_text());argv=argv[:argv.index('-drive')]
 argv[argv.index('-initrd')+1]=str(run/'initramfs.cpio.gz')
 argv[argv.index('-append')+1]='console=ttyAMA0 earlycon=pl011,0x09000000 rdinit=/init rmx3997_ak3_native=1 androidboot.slot_suffix=_b loglevel=7 panic=-1 nokaslr'
 argv[argv.index('-kernel')+1]=str(N/'out/arch/arm64/boot/Image')
 argv[argv.index('-machine')+1]='virt,gic-version=3,mte=on'
 argv += ['-device','ufs,id=rmxufs,serial=RMX3997-AK3-UFS,mcq=off']
 fault=None
 for ident,path,serial,ro in [('boot','boot.raw','BOOT',False),('init','init.raw','INIT',True),('data','data.ext4','DATA',False)]:
  if ident=='boot' and o.rollback_write_error:
   fault={'event':'pwritev','iotype':'write','errno':5,'once':True,'immediately':True}
   node={'driver':'raw','node-name':ident,'file':{'driver':'blkdebug','image':{'driver':'file','filename':str(run/path)},'inject-error':[fault]}}
   argv += ['-blockdev',json.dumps(node,separators=(',',':'))]
  else:
   argv += ['-drive',f'file={run/path},if=none,format=raw,id={ident}'+(',readonly=on' if ro else '')]
  argv += ['-device',f'ufs-lu,drive={ident},lun='+str({'boot':0,'init':1,'data':2}[ident])]
 (run/'qemu-argv.json').write_text(json.dumps(argv,indent=2)+'\n')
 # A dedicated canonical supervisor owns cleanup, including orphaned descendants.
 # Keep this guest's 240-second deadline; memory/swap policy stays canonical.
 command=['/usr/bin/python3',str(R/'resource_guard.py'),'--timeout','240','--report',str(run/'guard-result.json'),'--']+argv
 record={'package_sha256':digest(package),'kernel_sha256':digest(N/'out/arch/arm64/boot/Image'),'init_sha256':digest(R/'init'),'argv':argv,'guard_argv':command,'guard_sha256':digest(R/'resource_guard.py'),'formatter_argv':fmt,'guest_only':True,'timeout_seconds':240,'rollback_write_error':fault}
 start=time.monotonic()
 with (run/'console.log').open('xb') as log:
  proc=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
 report=json.loads((run/'guard-result.json').read_text())
 record.update(exit_code=proc.returncode,elapsed_seconds=time.monotonic()-start,
               memory_floor_bytes=report['min_available_kib']*1024,
               minimum_available_bytes=report['minimum_available_kib']*1024 if report['minimum_available_kib'] is not None else None,
               forgejo_report=report)
 if report['aborted']:record['abort']=report['reason']
 (run/'execution.json').write_text(json.dumps(record,indent=2)+'\n')
 console=(run/'console.log').read_text(errors='replace').replace('\r','')
 match=re.search('RMX_NATIVE_KERNEL_LOG_BEGIN\n(.*?)\nRMX_NATIVE_KERNEL_LOG_END',console,re.S)
 if match:(run/'kernel.log').write_text(match[1]+'\n')
 (run/'retained-adb').mkdir();runlog(['/usr/bin/debugfs','-R','rdump /adb '+str(run/'retained-adb'),str(run/'data.ext4')],run/'debugfs.log')
 backups=list((run/'retained-adb').rglob('boot_b.before.img'))
 checks={'qemu_exit_zero':proc.returncode==0,'no_abort':'abort' not in record,'entry_exit_zero':'RMX_NATIVE_ENTRY_EXIT=0' in console,'guest_pass':'RMX_NATIVE_RESULT=PASS' in console,'kernel_log':bool(match),'full_boot_hash':digest(run/'boot.raw')==EXPECTED_PAYLOAD,'readonly_init_unchanged':digest(run/'init.raw')==EXPECTED_INIT,'one_retained_backup':len(backups)==1,'retained_backup_stock':len(backups)==1 and digest(backups[0])==EXPECTED_STOCK,'original_stock_preserved':digest(STOCK)==EXPECTED_STOCK,'original_init_preserved':digest(INIT)==EXPECTED_INIT}
 if o.rollback_write_error:
  # The installation must FAIL with code70, while restoration independently
  # passes. Do not relabel the guest's generic installation-FAIL as success.
  del checks['entry_exit_zero'];del checks['guest_pass'];del checks['full_boot_hash']
  checks.update(expected_failed_install_exit70='RMX_NATIVE_ENTRY_EXIT=70' in console,
                rollback_verified_log='ROLLBACK VERIFIED' in console,
                target_restored_stock=digest(run/'boot.raw')==EXPECTED_STOCK)
 result={'status':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'scope':'actual packaged entry and Android adapter in ARM64 virtual guest; synthetic properties; actual unchanged production binary; not phone boot validation','package_sha256':record['package_sha256'],'kernel_sha256':record['kernel_sha256']}
 if o.rollback_write_error:
  result['case']='native rollback after one injected boot write EIO'
  result['expected_installer_exit_code']=70
  result['installation_result']='FAIL by injected fault; rollback acceptance is evaluated separately'
 (run/'results.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));return 0 if result['status']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
