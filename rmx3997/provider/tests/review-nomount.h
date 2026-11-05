/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual shutdown/dispatch/materializer bodies. pthread SRCU/lock and VFS
 * ownership shims exercise ordering; they do not certify kernel VFS/RCU. */
#include <assert.h>
#include <stdlib.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <stdatomic.h>
#include <pthread.h>
#include <stdio.h>
#include <errno.h>
#include <unistd.h>
#define READ_ONCE(x) __atomic_load_n(&(x),__ATOMIC_ACQUIRE)
#define WRITE_ONCE(x,v) __atomic_store_n(&(x),(v),__ATOMIC_RELEASE)
#define smp_load_acquire(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
#define smp_store_release(p,v) __atomic_store_n((p),(v),__ATOMIC_RELEASE)
#define cmpxchg(p,o,n) __sync_val_compare_and_swap((p),(o),(n))
#define unlikely(x) (x)
#define WARN_ON_ONCE(x) assert(!(x))
#define atomic_read(p) atomic_load(p)
#define atomic_inc(p) atomic_fetch_add(p,1)
#define atomic_dec(p) atomic_fetch_sub(p,1)
#define mutex_lock pthread_mutex_lock
#define mutex_unlock pthread_mutex_unlock
#define spin_lock pthread_mutex_lock
#define spin_unlock pthread_mutex_unlock
#define container_of(p,t,m) ((t*)((char*)(p)-offsetof(t,m)))
struct list_head {struct list_head *next,*prev;};
static void init_list(struct list_head *h) {h->next=h->prev=h;}
static void add_list(struct list_head *n,struct list_head *h) {n->prev=h->prev;n->next=h;h->prev->next=n;h->prev=n;}
#define list_for_each_entry(p,h,m) for(p=container_of((h)->next,__typeof__(*p),m);&(p)->m!=(h);p=container_of((p)->m.next,__typeof__(*p),m))
#define list_for_each_entry_rcu list_for_each_entry
#define for_each_alias(d,i) list_for_each_entry(d,&(i)->aliases,alias)
static void rcu_read_lock(void) {} static void rcu_read_unlock(void) {}
static pthread_mutex_t nm_mutex=PTHREAD_MUTEX_INITIALIZER,nm_shutdown_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_rwlock_t nm_materializers=PTHREAD_RWLOCK_INITIALIZER;
static bool nm_shutdown_released;
static int srcu_read_lock(pthread_rwlock_t *l) {pthread_rwlock_rdlock(l);return 0;}
static void srcu_read_unlock(pthread_rwlock_t *l,int i) {(void)i;pthread_rwlock_unlock(l);}
static void synchronize_srcu(pthread_rwlock_t *l) {pthread_rwlock_wrlock(l);pthread_rwlock_unlock(l);}
struct inode;struct super_block;
struct super_operations {int (*drop_inode)(struct inode*);void (*evict_inode)(struct inode*);};
struct inode_operations {int magic;};struct file_operations {int magic;};
struct dentry_operations {void *d_hash,*d_compare,*d_delete,*d_prune,*d_real;int (*d_revalidate)(void),(*d_weak_revalidate)(void);};
struct xattr_handler {int dummy;};
struct super_block {const struct super_operations *s_op;const struct xattr_handler **s_xattr;pthread_mutex_t s_inode_list_lock;struct list_head s_inodes;int active;};
struct inode {struct super_block *i_sb;const struct inode_operations *i_op;const struct file_operations *i_fop;struct list_head i_sb_list,aliases;pthread_mutex_t i_lock;bool virtual;int i_nlink,i_data;};
struct dentry {const struct dentry_operations *d_op;unsigned int d_flags;pthread_mutex_t d_lock;struct list_head alias;};
struct nm_dir_ops {struct inode_operations fake_iop;struct file_operations fake_fop;struct dentry_operations fake_dops;const struct inode_operations *orig_iop;const struct file_operations *orig_fop;const struct dentry_operations *orig_dops;};
struct nm_sop {struct super_operations fake_sop;const struct super_operations *orig_sop;const struct xattr_handler **orig_xattr,**fake_xattr;struct super_block *sb;atomic_int virtual_inodes;bool retired;struct list_head list;};
static struct list_head nm_sb_list;
static struct nm_sop records[2];static struct super_block blocks[2];static struct inode nodes[2];
static struct nm_dir_ops ops;static struct dentry alias;
static int nm_d_revalidate(void) {return 1;}
static const struct dentry_operations nm_dops={.d_revalidate=nm_d_revalidate},nm_owned_dops={.d_revalidate=nm_d_revalidate};
#define DCACHE_OP_HASH 1
#define DCACHE_OP_COMPARE 2
#define DCACHE_OP_REVALIDATE 4
#define DCACHE_OP_WEAK_REVALIDATE 8
#define DCACHE_OP_DELETE 16
#define DCACHE_OP_PRUNE 32
#define DCACHE_OP_REAL 64
#define DCACHE_DONTCACHE 128
static struct nm_dir_ops *nm_get_nm_iop(const struct inode_operations *p) {return p&&p->magic==1?container_of(p,struct nm_dir_ops,fake_iop):NULL;}
static struct nm_dir_ops *nm_get_nm_fop(const struct file_operations *p) {return p&&p->magic==1?container_of(p,struct nm_dir_ops,fake_fop):NULL;}
static const struct dentry_operations *nm_get_orig_dops(struct nm_dir_ops *p) {return p->orig_dops;}
static int nm_inode_is_virtual(struct inode *p) {return p->virtual;}
static int inode_unhashed(struct inode *p) {(void)p;return 0;}
static int real_drops,real_evictions,virtual_evictions,clears,flushes,put_refs;
static atomic_int pins_released,started,allow_finish;
static int orig_drop(struct inode *p) {(void)p;real_drops++;return 7;}
static void orig_evict(struct inode *p) {(void)p;real_evictions++;}
static const struct super_operations orig_sop={orig_drop,orig_evict};
static const struct inode_operations orig_iop={0},virtual_iop={2};
static const struct file_operations orig_fop={0};
static int orig_revalidate(void) {return 2;}
static const struct dentry_operations orig_dops={.d_hash=(void*)1,.d_revalidate=orig_revalidate};
static const struct xattr_handler *orig_xattrs[1],*fake_xattrs[1];
static void nm_destroy_virtual_inode(struct inode *p) {assert(p->virtual);p->virtual=false;virtual_evictions++;}
static void nm_destroy_hijacked_inode(struct inode *p) {(void)p;}
static void truncate_inode_pages_final(void *p) {(void)p;}
static void clear_inode(struct inode *p) {(void)p;}
static void dput(void *p) {if(p)put_refs++;}
static void path_put(void *p) {(void)p;put_refs++;}
static void nm_dir_put(void *p) {if(p)put_refs++;}
static void kfree(void *p) {free(p);}
#define ERR_PTR(n) ((void*)(intptr_t)(n))
#define NM_CLEAR_UIDS 1
#define NM_CLEAR_RULES 2
static int nm_reclaim_work;
static void nm_clear_state(int flags) {assert(flags==3);assert(!pthread_mutex_trylock(&nm_mutex));pthread_mutex_unlock(&nm_mutex);clears++;}
static void flush_work(void *p) {(void)p;flushes++;}
static void shrink_dcache_sb(struct super_block *p) {(void)p;assert(!pthread_mutex_trylock(&nm_mutex));pthread_mutex_unlock(&nm_mutex);}
static void deactivate_super(struct super_block *p) {assert(!pthread_mutex_trylock(&nm_mutex));pthread_mutex_unlock(&nm_mutex);assert(p->active>0);p->active--;atomic_fetch_add(&pins_released,1);}
struct nm_rule_info {char *r_name;void *saved_parent,*this_dir;struct {void *dentry;} r_path;};
static struct dentry *__nm_materialize_rule(struct inode *dir,struct dentry *d,struct nm_rule_info *r)
{(void)dir;(void)d;(void)r;atomic_store(&started,1);while(!atomic_load(&allow_finish))usleep(100);atomic_fetch_add(&records[1].virtual_inodes,1);nodes[1].virtual=true;return NULL;}
struct notifier_block {int dummy;};
#define SYS_RESTART 1
#define SYS_HALT 2
#define SYS_POWER_OFF 3
#define NOTIFY_DONE 0
/* CASES */
static void *materialize(void *p) {struct nm_rule_info rule={0};(void)p;assert(!nm_materialize_rule(&nodes[1],NULL,&rule));return NULL;}
static void *shutdown_thread(void *p) {(void)p;nm_reboot_notify(NULL,SYS_POWER_OFF,NULL);return NULL;}
int main(void)
{
 alarm(15);
 for(int round=0;round<100;round++) {
  pthread_t producer,shutdown1,shutdown2;
  init_list(&nm_sb_list);nm_shutdown_released=false;clears=flushes=real_drops=real_evictions=virtual_evictions=put_refs=0;
  atomic_store(&pins_released,0);atomic_store(&started,0);atomic_store(&allow_finish,0);
  for(int i=0;i<2;i++) {
   records[i]=(struct nm_sop){.orig_sop=&orig_sop,.sb=&blocks[i],.orig_xattr=orig_xattrs,.fake_xattr=fake_xattrs};
   records[i].fake_sop=(struct super_operations){nm_hijacked_drop_inode,nm_hijacked_evict_inode};
   atomic_init(&records[i].virtual_inodes,0);add_list(&records[i].list,&nm_sb_list);
   blocks[i]=(struct super_block){.s_op=&records[i].fake_sop,.s_xattr=fake_xattrs,.active=2};pthread_mutex_init(&blocks[i].s_inode_list_lock,NULL);init_list(&blocks[i].s_inodes);
   nodes[i]=(struct inode){.i_sb=&blocks[i],.i_nlink=1,.i_op=&virtual_iop};pthread_mutex_init(&nodes[i].i_lock,NULL);init_list(&nodes[i].aliases);add_list(&nodes[i].i_sb_list,&blocks[i].s_inodes);
  }
  ops=(struct nm_dir_ops){.fake_iop={1},.fake_fop={1},.fake_dops={.d_revalidate=nm_d_revalidate},.orig_iop=&orig_iop,.orig_fop=&orig_fop,.orig_dops=&orig_dops};
  nodes[0].i_op=&ops.fake_iop;nodes[0].i_fop=&ops.fake_fop;
  alias=(struct dentry){.d_op=&ops.fake_dops,.d_flags=DCACHE_OP_REVALIDATE|DCACHE_DONTCACHE};pthread_mutex_init(&alias.d_lock,NULL);add_list(&alias.alias,&nodes[0].aliases);
  nm_reboot_notify(NULL,99,NULL);assert(!nm_shutdown_released&&!clears);
  pthread_create(&producer,NULL,materialize,NULL);while(!atomic_load(&started))usleep(100);
  pthread_create(&shutdown1,NULL,shutdown_thread,NULL);while(!READ_ONCE(nm_shutdown_released))usleep(100);
  pthread_create(&shutdown2,NULL,shutdown_thread,NULL);assert(!atomic_load(&pins_released));
  atomic_store(&allow_finish,1);pthread_join(producer,NULL);pthread_join(shutdown1,NULL);pthread_join(shutdown2,NULL);
  assert(clears==1&&flushes==1&&atomic_load(&pins_released)==2);
  assert(blocks[0].active==1&&blocks[1].active==1&&blocks[0].s_op==&orig_sop);
  assert(blocks[1].s_op==&records[1].fake_sop); /* open virtual inode needs cleanup */
  assert(nodes[0].i_op==&orig_iop&&nodes[0].i_fop==&orig_fop);
  assert(alias.d_op==&orig_dops&&alias.d_flags==(DCACHE_OP_REVALIDATE|DCACHE_OP_HASH));
  assert(blocks[0].s_xattr==orig_xattrs&&blocks[1].s_xattr==orig_xattrs);
  assert(nm_hijacked_drop_inode(&nodes[0])==7);nm_hijacked_evict_inode(&nodes[0]);assert(real_evictions==1);
  nm_hijacked_evict_inode(&nodes[1]);assert(virtual_evictions==1&&blocks[1].s_op==&orig_sop);
  struct nm_rule_info late={.r_name=strdup("late"),.saved_parent=(void*)1,.this_dir=(void*)1,.r_path={(void*)1}};
  assert(nm_materialize_rule(&nodes[0],NULL,&late)==ERR_PTR(-ESHUTDOWN));assert(put_refs==3);
  nm_shutdown_release();assert(atomic_load(&pins_released)==2);
  deactivate_super(&blocks[0]);deactivate_super(&blocks[1]);assert(!blocks[0].active&&!blocks[1].active);
  for(int i=0;i<2;i++){pthread_mutex_destroy(&blocks[i].s_inode_list_lock);pthread_mutex_destroy(&nodes[i].i_lock);}pthread_mutex_destroy(&alias.d_lock);
 }
 puts("PASS100 actual shutdown/dispatch/materializer cycles: SRCU drain, concurrent repeated shutdown, native hook restore, late virtual eviction, exactly-once pin release outside mutex");
 return 0;
}
