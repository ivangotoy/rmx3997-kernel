#!/usr/bin/python3
"""Focused actual-function host shims, not VFS/BPF/LSM runtime certification."""
import argparse,hashlib,importlib.util,json,subprocess
from pathlib import Path
spec=importlib.util.spec_from_file_location('f',Path(__file__).with_name('test-full-feature-components.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
repo=Path(__file__).resolve().parents[2]
P=m.PRELUDE+r'''
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define likely(x) (x)
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
'''

def bpf():
 s=(repo/'net/core/skmsg.c').read_text()
 decl=s[s.index('struct sk_psock_parser {'):s.index('static struct strparser *sk_psock_strp')]
 return P+r'''
#define CONFIG_BPF_STREAM_PARSER 1
#define IS_ENABLED(x) (x)
#define GFP_ATOMIC 0
#define __GFP_NOWARN 0
#define BUILD_BUG_ON(x) _Static_assert(!(x),"prefix")
struct sock {int id;};struct bpf_prog {int answer;};
struct sk_buff {int len;struct sock *sk;};
struct sk_psock {struct sock *sk;struct {struct bpf_prog *stream_parser;} progs;int enabled;};
struct strparser {int done;};
static int fail;
static void *kzalloc_node(size_t n,int f,int node) {if(fail){fail=0;return NULL;}return calloc(1,n);}
#define rcu_read_lock() ((void)0)
#define rcu_read_unlock() ((void)0)
#define SK_PSOCK_RX_STRP_ENABLED 1
#define sk_psock_test_state(p,b) ((p)->enabled)
#define strp_done(p) ((p)->done++)
static int bpf_prog_run_pin_on_cpu(struct bpf_prog *p,struct sk_buff *b) {assert(b->sk && b->sk->id==42);return p->answer;}
'''+decl+''.join(m.function(s,n) for n in ['sk_psock_strp','sk_psock_alloc','sk_psock_strp_parse','sk_psock_done_strp'])+r'''
int main(void) {
 fail=1;assert(!sk_psock_alloc(0));
 for(int i=0;i<1000;i++) {
  struct sk_psock *p=sk_psock_alloc(0);struct sock sk={42};struct bpf_prog prog={17};
  struct sk_buff skb={30,NULL};assert(p);p->sk=&sk;
  assert(sk_psock_strp_parse(sk_psock_strp(p),&skb)==30);
  p->progs.stream_parser=&prog;assert(sk_psock_strp_parse(sk_psock_strp(p),&skb)==17);assert(!skb.sk);
  sk_psock_done_strp(p);assert(!sk_psock_strp(p)->done);
  p->enabled=1;sk_psock_done_strp(p);assert(sk_psock_strp(p)->done==1);
  free(p);
 }
 puts("PASS private wrapper allocation/failure, callback container binding, conditional parser teardown x1000");
}
'''

def nomount():
 s=(repo/'fs/nomount/nomount.c').read_text();h=(repo/'fs/nomount/nomount.h').read_text()
 def struct(name):
  start=h.index('struct '+name+' {');end=h.index('\n};',start)+3;return h[start:end]+'\n'
 return P+r'''
typedef uint16_t u16;
#define GFP_ATOMIC 0
#define __init
#define SYS_RESTART 1
#define SYS_HALT 2
#define SYS_POWER_OFF 3
#define NOTIFY_DONE 0
#define NM_CLEAR_UIDS 1
#define NM_CLEAR_RULES 2
#define NM_FLAG_IS_DIR 1
#define KERNEL_VERSION(a,b,c) (((a)<<16)|((b)<<8)|(c))
#define LINUX_VERSION_CODE KERNEL_VERSION(5,15,197)
struct super_block {int id;};struct inode {bool virt;};
struct dentry {struct dentry *d_parent;struct {char *name;unsigned len;} d_name;struct super_block *d_sb;struct inode *inode;unsigned d_seq;int refs;bool unlinked,positive,symlink;};
struct path {void *mnt;struct dentry *dentry;};
struct nm_dir_node {int refs;};
'''+struct('nm_rule')+struct('nm_rule_info')+r'''
struct nm_leaf {unsigned long v_ino;struct nm_dir_node *this_dir;};
static struct nm_rule *selected;
static struct nm_rule *nm_select_rule(struct nm_leaf *l,uid_t u) {return selected;}
#define raw_seqcount_begin(p) (*(p))
#define read_seqcount_retry(p,seq) (*(p)!=(seq))
#define d_unlinked(p) ((p)->unlinked)
static struct dentry *dget(struct dentry *d) {if(d)d->refs++;return d;}
static void dput(struct dentry *d) {if(d){assert(d->refs>0);d->refs--;}}
#define path_get(p) dget((p)->dentry)
#define atomic_inc(p) (++*(p))
static int fail_alloc;
static void *kmemdup(const void *p,size_t n,int f) {if(fail_alloc){fail_alloc=0;return NULL;}void *q=malloc(n);memcpy(q,p,n);return q;}
static struct dentry *lookup_result;
static struct dentry *lookup_one_len_unlocked(const char *n,struct dentry *parent,int len) {assert(len==3 && !memcmp(n,"foo",3));return dget(lookup_result);}
#define IS_ERR(p) ((p)==NULL)
#define PTR_ERR(p) (-ENOENT)
#define d_is_positive(p) ((p)->positive)
#define d_is_symlink(p) ((p)->symlink)
#define d_backing_inode(p) ((p)->inode)
#define nm_inode_is_virtual(p) ((p)->virt)
'''+''.join(m.function(s,n) for n in ['nm_path_unchanged','nm_resolve_rule_from_leaf','nm_rebind_path','nm_rule_heap_size','nm_copy_rule'])+r'''
static bool nm_shutdown_released;
static int cleared,flushed;
static void nm_clear_state(int flags) {assert(flags==(NM_CLEAR_UIDS|NM_CLEAR_RULES));cleared++;}
#define flush_work(p) (flushed++)
static int nm_reclaim_work;
struct notifier_block {int (*notifier_call)(struct notifier_block *,unsigned long,void *);};
'''+m.function(s,'nm_shutdown_release')+m.function(s,'nm_reboot_notify')+r'''
int main(void) {
 (void)nm_reclaim_work;
 struct super_block sb={1},wrong={2};struct inode inode={0};
 struct dentry parent={.refs=1},old={.d_parent=&parent,.d_name={"foo",3},.d_sb=&sb,.refs=1,.positive=true,.inode=&inode};
 struct dentry newer=old;struct nm_rule rule={.r_path={NULL,&old},.r_parent=&parent,.r_name="foo",.r_name_len=3,.r_len=4};
 selected=&rule;struct nm_leaf leaf={.v_ino=7};struct nm_rule_info info={0};
 assert(nm_resolve_rule_from_leaf(&leaf,10000,&info)==1);assert(!info.r_name);dput(info.r_path.dentry);
 old.unlinked=true;fail_alloc=1;assert(nm_resolve_rule_from_leaf(&leaf,10000,&info)==-ENOMEM);
 for(int i=0;i<1000;i++) {
  memset(&info,0,sizeof(info));assert(nm_resolve_rule_from_leaf(&leaf,10000,&info)==1);
  assert(info.saved_parent==&parent && !memcmp(info.r_name,"foo",3));
  lookup_result=&newer;assert(!nm_rebind_path(&info));assert(info.r_path.dentry==&newer);
  dput(info.r_path.dentry);dput(info.saved_parent);free(info.r_name);
  struct nm_rule copy;char heap[7];assert(nm_copy_rule(&copy,&rule,heap,"/foo")==heap+7);
  assert(copy.r_name==heap+4 && !memcmp(copy.r_name,"foo",3));dput(copy.r_path.dentry);dput(copy.r_parent);
 }
 for(int bad=0;bad<4;bad++) {
  memset(&info,0,sizeof(info));assert(nm_resolve_rule_from_leaf(&leaf,10000,&info)==1);
  newer.positive=bad!=0;newer.symlink=bad==1;newer.d_sb=bad==2?&wrong:&sb;inode.virt=bad==3;
  assert(nm_rebind_path(&info)==-ENOENT);dput(info.r_path.dentry);dput(info.saved_parent);free(info.r_name);
 }
 assert(old.refs==1 && newer.refs==1 && parent.refs==1);
 nm_reboot_notify(NULL,99,NULL);assert(!cleared);
 nm_reboot_notify(NULL,SYS_RESTART,NULL);nm_reboot_notify(NULL,SYS_HALT,NULL);nm_reboot_notify(NULL,SYS_POWER_OFF,NULL);
 assert(cleared==1 && flushed==1 && nm_shutdown_released);
 puts("PASS path snapshot/allocation failure, rebind validation, copied-rule refs x1000 and explicit idempotent shutdown");
}
'''

def nomount_init():
 s=(repo/'fs/nomount/nomount.c').read_text()
 assert 'nm_shutdown_sync_fs' not in s
 assert 'fake_sop.sync_fs =' not in s
 return P+r'''
#define __init
#define __exit
#define SYS_RESTART 1
#define SYS_HALT 2
#define SYS_POWER_OFF 3
#define NOTIFY_DONE 0
#define NM_CLEAR_UIDS 1
#define NM_CLEAR_RULES 2
#define NM_CLEAR_EXIT 4
#define nm_info(...) ((void)0)
#define nm_err(...) ((void)0)
struct notifier_block {int (*notifier_call)(struct notifier_block *,unsigned long,void *);};
static int notifier_count,key_count,fail_notifier,fail_key,clear_flags,clears,flushes,barriers;
static int nm_reclaim_work,nm_key_type;
static bool nm_shutdown_released;
static int register_reboot_notifier(struct notifier_block *p) {if(fail_notifier)return -ENOMEM;notifier_count++;return 0;}
static void unregister_reboot_notifier(struct notifier_block *p) {assert(notifier_count==1);notifier_count--;}
static int register_key_type(int *p) {if(fail_key)return -ENOMEM;key_count++;return 0;}
static void unregister_key_type(int *p) {assert(key_count==1);key_count--;}
static void nm_clear_state(int f) {clear_flags=f;clears++;}
#define flush_work(p) (flushes++)
#define rcu_barrier() (barriers++)
'''+m.function(s,'nm_shutdown_release')+m.function(s,'nm_reboot_notify')+r'''
static struct notifier_block nm_reboot_notifier={.notifier_call=nm_reboot_notify};
'''+m.function(s,'nomount_init')+m.function(s,'nomount_exit')+r'''
int main(void) {
 (void)nm_reclaim_work;
 fail_notifier=1;assert(nomount_init()==-ENOMEM && !key_count && !notifier_count);
 fail_notifier=0;fail_key=1;assert(nomount_init()==-ENOMEM && !key_count && !notifier_count);
 fail_key=0;assert(!nomount_init() && key_count==1 && notifier_count==1);
 nm_reboot_notifier.notifier_call(&nm_reboot_notifier,99,NULL);assert(!clears && !nm_shutdown_released);
 nm_reboot_notifier.notifier_call(&nm_reboot_notifier,SYS_POWER_OFF,NULL);
 assert(clears==1 && clear_flags==3 && flushes==1);
 nm_reboot_notifier.notifier_call(&nm_reboot_notifier,SYS_HALT,NULL);assert(clears==1);
 nomount_exit();assert(!key_count && !notifier_count && clear_flags==7 && clears==2 && flushes==2 && barriers==1);
 puts("PASS actual init failure unwind, notifier/key ownership, explicit shutdown, exit flush/RCU barrier; normal sync unchanged");
}
'''

def bbg():
 root=Path('/mnt/Users/ivan/Pictures/REALME/oplus_ossi_16_1791533415164_2611033311')
 scatter=(root/'MT6835_Android_scatter.txt').read_text()
 names=[line.split(':',1)[1].strip() for line in scatter.splitlines() if line.strip().startswith('partition_name:')]
 s=(repo/'security/baseband-guard/blkdev_helper.c').read_text();h=(repo/'security/baseband-guard/baseband_guard.h').read_text()
 table=h[h.index('static const char * const allowlist_names'):]
 allowed={'misc','metadata','userdata'}|{base+slot for base in ['boot','init_boot','vendor_boot','dtbo','vbmeta','vbmeta_system','vbmeta_vendor'] for slot in ['_a','_b']}
 cases='\n'.join('assert(partition_name_in_allowlist('+json.dumps(n)+','+str(len(n)+1)+')=='+str(int(n in allowed))+');' for n in names)
 return P+'#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))\n'+table+'\nchar *saved_command_line="";\n'+''.join(m.function(s,n) for n in ['slot_suffix_from_cmdline','partition_name_matches','partition_name_in_allowlist'])+r'''
int main(void) {
'''+cases+r'''
 assert(!partition_name_in_allowlist("md1img_a",9));assert(!partition_name_in_allowlist("nvram",6));
 assert(!partition_name_in_allowlist("boot_a_suffix",14));assert(!partition_name_in_allowlist("boot_a",6));
 saved_command_line="androidboot.slot_suffix=_a";
 assert(partition_name_in_allowlist("boot_a",7));assert(!partition_name_in_allowlist("boot_b",7));
 puts("PASS exact retained MT6835 scatter mapping; modem/NV/firmware/GPT denied, current donor slot policy preserved");
}
'''

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--only',choices=['bpf','nomount','bbg','nomount-init']);a=p.parse_args()
 out=Path(a.output);out.mkdir(exist_ok=False);results={}
 for name,build in [('bpf',bpf),('nomount',nomount),('bbg',bbg),('nomount-init',nomount_init)]:
  if a.only and a.only!=name:continue
  src=out/(name+'.c');src.write_text(build());binary=out/name
  argv=['/usr/bin/cc','-O2','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-fsanitize=undefined','-fno-sanitize-recover=all',str(src),'-o',str(binary)]
  with (out/(name+'.log')).open('x') as log:
   subprocess.run(argv,stdout=log,stderr=subprocess.STDOUT,check=True);subprocess.run([str(binary)],stdout=log,stderr=subprocess.STDOUT,check=True)
  results[name]={'argv':argv,'result':'PASS','fixture_sha256':hashlib.sha256(src.read_bytes()).hexdigest()}
 (out/'results.json').write_text(json.dumps(results,indent=2)+'\n');print(json.dumps(results,indent=2))
