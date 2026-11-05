#!/usr/bin/python3
"""Actual C regression fixtures with explicit host service shims; no runtime proof.

Run under resource-guard.py. Output directories must be new, disk-backed paths.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import importlib.util
spec = importlib.util.spec_from_file_location('components', Path(__file__).with_name('test-full-feature-components.py'))
components = importlib.util.module_from_spec(spec)
spec.loader.exec_module(components)
function = components.function
REPO = Path(__file__).resolve().parents[2]
PRELUDE = '#define _GNU_SOURCE\n' + components.PRELUDE + r'''
#include <sys/types.h>
#include <fcntl.h>
#define likely(x) (x)
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,y) ((x)=(y))
typedef unsigned char u8;
'''


def cpufreq():
    s=(REPO/'drivers/cpufreq/cpufreq.c').read_text()
    declarations=s[s.index('struct cpufreq_min_limit {'):s.index('static struct cpufreq_min_limit *cpufreq_min_limit_entry')]
    return PRELUDE + r'''
#define NR_CPUS 32
struct freq_qos_request { struct {int prio;} pnode; };
struct cpufreq_policy { unsigned *related_cpus; struct freq_qos_request *min_freq_req; };
#define cpumask_first(mask) (*(mask))
''' + declarations + ''.join(function(s,n) for n in ['cpufreq_min_limit_entry','cpufreq_min_limit','cpufreq_min_limit_remove']) + r'''
int main(void) {
 unsigned empty=32, bad=99, key=4;
 struct freq_qos_request req={{1000}};
 struct cpufreq_policy failed={&empty,NULL}, live={&key,&req}, foreign={&key,&req};
 for(int i=0;i<1000;i++) {
  cpufreq_min_limit_remove(&failed);assert(!cpufreq_min_limit(&failed));
  failed.related_cpus=&bad;cpufreq_min_limit_remove(&failed);assert(!cpufreq_min_limit(&failed));
  failed.related_cpus=&empty;
  assert(cpufreq_min_limit(&live)==&min_limits[4]);
  min_limits[4].limit=700;
  assert(!cpufreq_min_limit(&foreign));cpufreq_min_limit_remove(&foreign);
  assert(min_limits[4].owner==&live && min_limits[4].limit==700);
  cpufreq_min_limit_remove(&live);assert(!min_limits[4].owner);
  assert(cpufreq_min_limit(&foreign)->limit==INT_MAX);
  assert(min_limits[4].requested==1000);cpufreq_min_limit_remove(&foreign);
 }
 puts("PASS empty/invalid masks, init failure, ownership, cleanup and key reuse x1000");
}
'''

def sysctl():
    s=(REPO/'kernel/sysctl.c').read_text()
    source=(REPO/'net/ipv4/sysctl_net_ipv4.c').read_text()
    bound=next(x for x in source.splitlines() if x.startswith('static ') and 'tcp_plb_max_rounds =' in x)
    return PRELUDE + r'''
struct ctl_table {void *data; int maxlen; void *extra1,*extra2;};
struct do_proc_douintvec_minmax_conv_param {unsigned int *min,*max;};
''' + function(s,'do_proc_douintvec_conv') + function(s,'do_proc_douintvec_minmax_conv') + r'''
/* Parser shim; the production bound reader and converter are extracted above/below. */
static int do_proc_douintvec(struct ctl_table *t,int w,void *b,size_t *l,loff_t *p,
 int (*conv)(unsigned long *,unsigned int *,int,void *),void *param) {
 unsigned long val=strtoul(b,NULL,10); (void)l;(void)p;
 return conv(&val,t->data,w,param);
}
''' + function(s,'proc_dou8vec_minmax') + bound + r'''
int main(void) {
 u8 value=7;unsigned int zero=0;loff_t pos=0;size_t len=2;
 struct ctl_table t={&value,sizeof(value),&zero,&tcp_plb_max_rounds};
 _Static_assert(sizeof(tcp_plb_max_rounds)==sizeof(unsigned int),"bound width");
 char *values[]={"0","31","32","255","256"};
 for(int i=0;i<5;i++) {
  int ret=proc_dou8vec_minmax(&t,1,values[i],&len,&pos);
  if(i<2) {assert(!ret);assert(value==(i?31:0));}
  else {assert(ret<0);assert(value==31);}
 }
 puts("PASS actual proc_dou8vec_minmax unsigned bound and 0/31/32/255/256");
}
'''

def susfs(active=False):
    s=(REPO/'fs/susfs.c').read_text()
    section=s[s.index('#define SUSFS_PRIORITY_UID_FILTER_MIN_UID'):s.index('#endif // #ifdef CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER',s.index('#define SUSFS_PRIORITY_UID_FILTER_MIN_UID'))]
    observer=(REPO/'drivers/kernelsu/manager/pkg_observer.c').read_text()
    fixture = PRELUDE + r'''
#define CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER 1
#define __user
#define __rcu
#define GFP_KERNEL 0
#define __GFP_ZERO 0
#define BITS_TO_LONGS(n) (((n)+63)/64)
#define DEFINE_MUTEX(n) int n
#define mutex_lock(p) ((void)(p))
#define mutex_unlock(p) ((void)(p))
#define lockdep_is_held(p) 1
#define rcu_dereference_protected(p,c) (p)
#define rcu_dereference(p) (p)
#define rcu_assign_pointer(p,v) ((p)=(v))
#define synchronize_rcu() ((void)0)
#define kfree_rcu(p,m) free(p)
#define SUSFS_LOGI(...) ((void)0)
#define SUSFS_LOGE(...) ((void)0)
#define pr_info(...) ((void)0)
#define pr_warn(...) ((void)0)
#define set_bit(n,b) ((b)[(n)/64]|=1UL<<((n)%64))
#define test_bit(n,b) (!!((b)[(n)/64]&(1UL<<((n)%64))))
#define copy_from_user(d,s,n) (memcpy(d,s,n),0)
#define copy_to_user(d,s,n) (memcpy(d,s,n),0)
#define IS_ERR(p) ((p)==NULL)
#define PTR_ERR(p) (-ENOENT)
#define kfree(p) free(p)
#define kvfree(p) free(p)
#define vfree(p) free(p)
struct rcu_head {void *unused;};
typedef u64 atomic64_t;
#define ATOMIC64_INIT(v) (v)
#define atomic64_read(p) (*(p))
#define atomic64_inc(p) (++*(p))
static int fail_alloc;
static void *alloc(size_t n) {if(fail_alloc){fail_alloc=0;return NULL;}return calloc(1,n);}
#define kvmalloc(n,f) alloc(n)
#define kzalloc(n,f) alloc(n)
#define vmalloc(n) alloc(n)
struct st_susfs_priority_uid_filter {char app_strings[65536];int err;};
struct cred {int unused;};
static const struct cred credential;
static const struct cred *susfs_switch_to_ksu_domain(void) {return &credential;}
static void susfs_restore_creds(const struct cred *p) {assert(p==&credential);}
static char *strim(char *p) {while(*p==' ')p++;size_t n=strlen(p);while(n&&p[n-1]==' ')p[--n]=0;return p;}
static int kstrtoul(const char *p,int base,unsigned long *out) {char *end;*out=strtoul(p,&end,base);return *end?-EINVAL:0;}
static char packages[1024];static void (*read_hook)(void);
struct file {int unused;};static struct file file;
#define file_inode(fp) (fp)
#define i_size_read(fp) strlen(packages)
static struct file *filp_open(const char *p,int flags,int mode) {assert(!strcmp(p,"/data/system/packages.list"));return &file;}
#define filp_close(fp,x) ((void)(fp))
static int kernel_read(struct file *fp,void *b,size_t n,loff_t *pos) {memcpy(b,packages,n);if(read_hook){void (*hook)(void)=read_hook;read_hook=NULL;hook();}return n;}
void susfs_parse_priority_app_strings(void);
''' + section + r'''
#define PF_EXITING 1
#define PF_KTHREAD 2
#define FS_ISDIR 4
#define TWA_RESUME 0
#define TRACK_THRONE_FORCE_SYNCHRONOUS 0
struct {int flags;} task;
#define current (&task)
struct callback_head {void (*func)(struct callback_head *);};
static struct callback_head *queued;
static int task_work_add(void *t,struct callback_head *cb,int mode) {assert(!queued);queued=cb;return 0;}
static void track_throne(int mode) {}
struct fsnotify_mark {int unused;};struct inode {int unused;};
struct qstr {const char *name;unsigned len;};
''' + ''.join(function(observer,n) for n in ['ksu_track_throne_tw_func','ksu_defer_track_throne','ksu_handle_inode_event']) + r'''
static void event(void) {struct qstr name={"packages.list",13};ksu_handle_inode_event(NULL,0,NULL,NULL,&name,0);}
static void resume(void) {assert(queued);struct callback_head *cb=queued;queued=NULL;cb->func(cb);}
static void racing_event(void) {susfs_notify_priority_uid_update();}
static void racing_config(void) {susfs_priority_config_generation++;}
int main(void) {
 struct st_susfs_priority_uid_filter info={.app_strings="com.target"};void *arg=&info;
 strcpy(packages,"com.target 10001 0\n");susfs_set_priority_uid_filter(&arg);
 assert(!info.err && susfs_is_priority_uid_filtered(10001));
 strcpy(packages,"com.target 10002 0\ncom.unrelated 10001 0\n");event();
 assert(!susfs_is_priority_uid_filtered(10001));resume();
 assert(susfs_is_priority_uid_filtered(10002));assert(!susfs_is_priority_uid_filtered(10001));
 strcpy(packages,"com.unrelated 10002 0\n");event();resume();assert(!susfs_is_priority_uid_filtered(10002));
 strcpy(packages,"com.target 10003 0\n");event();resume();assert(susfs_is_priority_uid_filtered(10003));
 /* Allocation failure in task_work must invalidate the reused UID immediately. */
 fail_alloc=1;strcpy(packages,"com.unrelated 10003 0\n");event();assert(!queued);
 assert(!susfs_is_priority_uid_filtered(10003));
 strcpy(packages,"com.target 10004 0\n");event();read_hook=racing_event;resume();
 assert(!susfs_is_priority_uid_filtered(10004));event();resume();assert(susfs_is_priority_uid_filtered(10004));
 event();read_hook=racing_config;resume();assert(!susfs_is_priority_uid_filtered(10004));
 event();resume();assert(susfs_is_priority_uid_filtered(10004));
 task.flags=PF_EXITING;event();resume();assert(!susfs_is_priority_uid_filtered(10004));task.flags=0;
 event();resume();assert(susfs_is_priority_uid_filtered(110004));
 free(priority_uid_filter_bitmap);free(susfs_priority_app_strings);
 puts("PASS actual package producer/task_work + resolver: reassign/remove/reuse, failed allocation/exiting and stale snapshots");
}
'''

    if active:
        tracker=(REPO/'drivers/kernelsu/manager/throne_tracker.c').read_text()
        begin=fixture.index('static void ksu_track_throne_tw_func(')
        end=fixture.index('static void resume(void)',begin)
        fixture=fixture[:begin]+r'''
struct dentry {char d_iname[32];};
#define ksu_get_uid_t(uid) (uid)
#define current_uid() 1000
static char *dentry_path_raw(struct dentry *d,char *buf,size_t n) {strcpy(buf,"/data/system/packages.list");return buf;}
#define pr_err(...) ((void)0)
#define TRACK_THRONE_FROM_RENAMEAT 2
'''+''.join(function(tracker,n) for n in ['ksu_priority_uid_refresh','ksu_defer_priority_uid_refresh','ksu_handle_rename'])+r'''
static void event(void) {struct dentry old={"packages.list.tmp"},new={"packages.list"};ksu_handle_rename(&old,&new);}
'''+fixture[end:]
        fixture=fixture.replace('struct {int flags;} task;','struct {int flags;void *mm;} task={.mm=(void *)1};')
        fixture=fixture.replace('struct qstr {const char *name;unsigned len;};','struct qstr {const char *name;unsigned len;};')
        fixture=fixture.replace('actual package producer/task_work','actual 5.15 LSM rename producer/task_work')
    return fixture

def susfs_before_rename():
    fixture=susfs(True)
    return fixture[:fixture.index('int main(void)')]+r'''
int main(void) {
 struct st_susfs_priority_uid_filter info={.app_strings="com.target"};void *arg=&info;
 strcpy(packages,"com.target 10001 0\n");susfs_set_priority_uid_filter(&arg);
 assert(!info.err && susfs_is_priority_uid_filtered(10001));
 /* Actual LSM runs BEFORE final-name publication; the task_work runs AFTER. */
 event();assert(!susfs_is_priority_uid_filtered(10001));
 strcpy(packages,"com.target 10002 0\ncom.unrelated 10001 0\n");resume();
 assert(susfs_is_priority_uid_filtered(10002) && !susfs_is_priority_uid_filtered(10001));
 /* Keep helper coverage references; this fixture focuses on publication order. */
 (void)racing_event;(void)racing_config;
 free(priority_uid_filter_bitmap);free(susfs_priority_app_strings);
 puts("PASS active5.15 LSM invalidates before rename; writer task_work resolves after publication");
}
'''

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--only',choices=['cpufreq','sysctl','susfs','susfs-active','susfs-before-rename']);a=p.parse_args()
    out=Path(a.output);out.mkdir(exist_ok=False)
    results={}
    for name,make in [('cpufreq',cpufreq),('sysctl',sysctl),('susfs',susfs),('susfs-active',lambda:susfs(True)),('susfs-before-rename',susfs_before_rename)]:
        if a.only and name!=a.only:continue
        src=out/(name+'.c');src.write_text(make());binary=out/name
        argv=['/usr/bin/cc','-O2','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-fsanitize=undefined','-fno-sanitize-recover=all',str(src),'-o',str(binary)]
        with (out/(name+'.log')).open('w') as log:
            subprocess.run(argv,stdout=log,stderr=subprocess.STDOUT,check=True)
            subprocess.run([str(binary)],stdout=log,stderr=subprocess.STDOUT,check=True)
        results[name]={'argv':argv,'fixture_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'result':'PASS','log':str(out/(name+'.log'))}
    (out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
    print(json.dumps(results,indent=2))
