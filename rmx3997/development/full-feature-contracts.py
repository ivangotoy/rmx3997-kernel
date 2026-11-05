#!/usr/bin/python3
"""Freeze/recheck actual local source inputs and pinned primary contracts.

This pre-build check cannot certify compiled ABI, runtime or full parity.
No network, source updates, artifact publication or calibration overrides.
"""
import argparse,hashlib,importlib.util,json,os,subprocess,sys
from pathlib import Path
sys.dont_write_bytecode=True
REPO=Path(__file__).resolve().parents[2]
PRIMARY=Path('/home/build/Downloads/GKI_KernelSU_SUSFS')
PIN='bcc9c39fa0d58027739dae3cb07baa6e01c98db9'
BASE='45d11286dfb03dccc58624bbb1b560f4a2f1df67'
PUBLIC=['include/net/tcp.h','include/linux/tcp.h','include/linux/skbuff.h','include/net/inet_connection_sock.h','include/uapi/linux/inet_diag.h','android/abi_gki_aarch64.xml']
EXCLUDE={'rmx3997/development/full-feature-20261104-state.json'}
PINS={'wild-gki':'c6d44eb9110888ad0cbc8e172d0d64eaa7df3e1e','wild-oneplus':'11821d9e122629d0888382f588954ef79ee88af6','kernel-patches':'ee68218dc83b3e488ae619eb82e868859e8eb17d','aimax-fork':'51d8178a3cde8f529ef71c5592f05b9ae513f96a'}
def sha(raw):return hashlib.sha256(raw).hexdigest()
def git(root,*args):return subprocess.check_output(['git','-C',str(root),*args])
def source_identity():
 if git(REPO,'rev-parse','HEAD').decode().strip()!=BASE:raise ValueError('baseline changed')
 paths=set(git(REPO,'diff','--name-only','HEAD','-z').decode().split('\0'))|set(git(REPO,'ls-files','--others','--exclude-standard','-z').decode().split('\0'))
 return {p:sha((REPO/p).read_bytes()) for p in sorted(paths-EXCLUDE-{''}) if (REPO/p).is_file()}
def verify_sources(record,root=REPO):
 for name,expected in record['source_sha256'].items():
  p=root/name
  if not p.is_file() or sha(p.read_bytes())!=expected:raise ValueError('source changed: '+name)
def parse_config(text):
 result={}
 for line in text.splitlines():
  if line.startswith('CONFIG_') and '=' in line:k,v=line.split('=',1);result[k]=v
  elif line.startswith('# CONFIG_') and line.endswith(' is not set'):result[line[2:-11]]='n'
 return result

def verify_config(expected,actual):
 for k,v in expected.items():
  if actual.get(k,'n')!=v:raise ValueError('resolved config mismatch: '+k)
 protected={'CONFIG_KSU':'y','CONFIG_KSU_SUSFS':'y','CONFIG_LTO_CLANG_FULL':'y','CONFIG_CFI_CLANG':'y','CONFIG_MODVERSIONS':'y','CONFIG_MODULE_SIG_PROTECT':'y','CONFIG_F2FS_FS_DEDUP':'y','CONFIG_F2FS_FS_COMPRESSION_FIXED_OUTPUT':'y','CONFIG_ARM64_4K_PAGES':'y','CONFIG_ZRAM':'m'}
 for k,v in protected.items():
  if actual.get(k,'n')!=v:raise ValueError('compatibility config changed: '+k)

def primary_contracts(config):
 if git(PRIMARY,'rev-parse','HEAD').decode().strip()!=PIN:raise ValueError('primary pin changed')
 if git(PRIMARY,'status','--porcelain').strip():raise ValueError('shared checkout is dirty')
 # Imports read the immutable existing checkout; Python bytecode is disabled.
 sys.path.insert(0,str(PRIMARY/'tools'))
 import bakasu_contract,nomount_contract
 historical=bakasu_contract.validate_identity(bakasu_contract.identity())
 selection=bakasu_contract.active_selection(PRIMARY,'android12')
 identity=bakasu_contract.selected_identity(selection)
 root=json.loads((REPO/'rmx3997/development/root-sources.json').read_text())['BakaSU']
 if (identity['commit'],identity['version'])!=(root['commit'],root['version']):raise ValueError('primary root differs')
 contract=nomount_contract.load_contract(PRIMARY/'.github/config/nomount.json')
 asset=nomount_contract.vendored_asset(contract,PRIMARY)
 nomount_contract.verify_compiled_config(config)
 return {'primary_pin':PIN,'BakaSU_identity':identity,'BakaSU_historical_default':historical,'root_selection_scope':'Original primary android12 source selection validator only; no 5.10 kernel/profile/toolchain substitution','NoMount_contract':contract,'NoMount_verified_asset':str(asset),'scope':'Original primary metadata and archive validators. Adapted kernel source is deliberately not attested as the unchanged donor tree; runtime/calibration/source freshness beyond retained pins is not claimed.'}

def whitelist_contract(config):
 values=parse_config(config.read_text())
 expected=config.resolve().parent/'abi_symbollist.raw'
 if values.get('CONFIG_TRIM_UNUSED_KSYMS')!='y':raise ValueError('KMI trim disabled')
 if values.get('CONFIG_UNUSED_KSYMS_WHITELIST')!='"'+str(expected)+'"':raise ValueError('KMI whitelist is not bound to current stage')
 raw=expected.read_bytes()
 source=REPO/'rmx3997/config/abi-symbol-list.txt'
 if raw!=source.read_bytes():raise ValueError('KMI whitelist differs from canonical source; regenerate before freeze/build')
 return {'path':str(expected),'sha256':sha(raw),'source':str(source),'source_sha256':sha(source.read_bytes())}

def capture(config):
 sources=source_identity();values=parse_config(config.read_text());expected=parse_config((REPO/'rmx3997/development/features.config').read_text());verify_config(expected,values)
 for name in PUBLIC:
  if (REPO/name).read_bytes()!=git(REPO,'show',BASE+':'+name):raise ValueError('public contract changed: '+name)
 for directory,pin in PINS.items():
  if git(REPO/'.cache/parity-sources'/directory,'rev-parse','HEAD').decode().strip()!=pin:raise ValueError('donor pin mismatch: '+directory)
 return {'kmi_whitelist':whitelist_contract(config),'baseline':BASE,'source_sha256':sources,'source_selection_sha256':sha(json.dumps(sources,sort_keys=True,separators=(',',':')).encode()),'resolved_config_path':str(config),'resolved_config_sha256':sha(config.read_bytes()),'requested_config':expected,'donor_pins':PINS,'primary_contracts':primary_contracts(values),'public_contracts':{p:sha((REPO/p).read_bytes()) for p in PUBLIC},'result':'SOURCE/CONFIG/PRIMARY METADATA PASS; no binary/runtime or FULL claim'}

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--capture',type=Path);p.add_argument('--verify',type=Path);p.add_argument('--config',type=Path);a=p.parse_args()
 if bool(a.capture)==bool(a.verify):p.error('choose capture or verify')
 if a.capture:
  if not a.config:p.error('--config required')
  record=capture(a.config)
  with a.capture.open('x') as f:json.dump(record,f,indent=2);f.write('\n')
 else:
  record=json.loads(a.verify.read_text());verify_sources(record)
  if source_identity()!=record['source_sha256']:raise ValueError('changed source set')
  config=Path(record['resolved_config_path'])
  if sha(config.read_bytes())!=record['resolved_config_sha256']:raise ValueError('resolved config changed')
  verify_config(record['requested_config'],parse_config(config.read_text()))
  if record.get('kmi_whitelist')!=whitelist_contract(config):raise ValueError('KMI whitelist provenance changed')
 print(record['result'])
