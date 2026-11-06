#!/usr/bin/python3
"""Cheap checks of actual pinned protocol definitions and path validator.

VFS lifetime acceptance is owned by nomount-runtime.inc in the new Image guest.
"""
from pathlib import Path
import argparse,hashlib,json,os,re,subprocess
R=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();D=a.output.resolve();D.mkdir()
k=(R/'fs/nomount/nomount.h').read_text();u=(R/'rmx3997/development/nomount-userspace/nm.h').read_text();c=(R/'fs/nomount/nomount.c').read_text()
ke=re.findall(r'NM_CMD_[A-Z_]+',k[k.index('enum {'):k.index('struct nm_payload')]);ue=re.findall(r'NM_CMD_[A-Z_]+',u[u.index('enum {'):u.index('enum nm_cli_action')]);assert ke==ue
# Compile the actual two definitions independently with their native types.
for name,source in [('kernel',k),('userspace',u)]:
 structs=source[source.index('struct nm_payload {'):source.index('/* * Compat macros') if name=='kernel' else source.index('struct nm_args {')]
 if name=='userspace':structs=structs[:structs.index('struct nm_workspace')]+structs[structs.index('struct nm_rule_hdr'):]
 code='#include <stdint.h>\n#include <stddef.h>\ntypedef uint64_t u64;typedef uint32_t u32;typedef uint16_t u16;\n'+structs+'\n_Static_assert(sizeof(struct nm_payload)==4096,"size");\n_Static_assert(offsetof(struct nm_payload,buffer)==28,"offset");\n_Static_assert(sizeof(struct nm_rule_hdr)==24,"rule size");\n_Static_assert(sizeof(struct nm_del_hdr)==18,"del size");\nint main(void){return 0;}\n'
 (D/(name+'.c')).write_text(code)
 subprocess.run(['/usr/bin/cc','-std=gnu11','-Wall','-Werror',str(D/(name+'.c')),'-o',str(D/name)],check=True);subprocess.run([str(D/name)],check=True)
start=c.index('static bool nm_diagnostic_path');end=c.index('static int nm_diagnostic_rule',start)
code='#include <stdint.h>\n#include <stdbool.h>\n#include <string.h>\n#include <assert.h>\ntypedef uint16_t u16;\n'+c[start:end]+'''int main(void) {
 const char *yes[]={"/a","/data/nmfixture/file","/a.b/c-d"};
 const char *no[]={"/","relative","/a/","/a//b","/a/./b","/a/../b"};
 for(unsigned i=0;i<sizeof(yes)/sizeof(*yes);i++)assert(nm_diagnostic_path(yes[i],strlen(yes[i])));
 for(unsigned i=0;i<sizeof(no)/sizeof(*no);i++)assert(!nm_diagnostic_path(no[i],strlen(no[i])));
 assert(!nm_diagnostic_path("/abc\\0def",8)); return 0;
}\n'''
(D/'path.c').write_text(code);subprocess.run(['/usr/bin/cc','-std=gnu11','-Wall','-Werror',str(D/'path.c'),'-o',str(D/'path')],check=True);subprocess.run([str(D/'path')],check=True)
record={'status':'PASS','commands_order':ke,'packed_payload_size':4096,'buffer_offset':28,'rule_header_size':24,'delete_header_size':18,'actual_path_validator_cases':10,'runtime_VFS_test':'PENDING_ACTUAL_IMAGE_GUEST','source_sha256':{str(x.relative_to(R)):hashlib.sha256(x.read_bytes()).hexdigest() for x in [R/'fs/nomount/nomount.c',R/'fs/nomount/nomount.h',R/'rmx3997/development/nomount-userspace/nm.h']}}
(D/'result.json').write_text(json.dumps(record,indent=2));print('NOMOUNT_PINNED_PROTOCOL_AND_PATH_TESTS_PASS')
