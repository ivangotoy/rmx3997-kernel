/* SPDX-License-Identifier: GPL-2.0-only */
/* Source-body allocation/thread/proc ownership fixture, no real kthreads. */
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <stdio.h>
#include <errno.h>
#define CONFIG_OPLUS_FEATURE_MM_OSVELTE 1
#define IS_ENABLED(x) (x)
#define IS_ERR(p) ((uintptr_t)(p)>(uintptr_t)-4096)
#define IS_ERR_OR_NULL(p) (!(p)||IS_ERR(p))
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define GFP_KERNEL 0
#define DEFAULT_NR_KCOMPRESSD 1
#define INIT_QUEUE_SIZE 4096
#define COMFD1_KCOMPRESSED 1
#define KCOMPRESSD_NOT_STARTED 0
#define KCOMPRESSD_RUNNING 1
#define pr_err(...) ((void)0)
#define pr_info(...) ((void)0)
#define atomic_set(p,v) (*(p)=(v))
#define init_waitqueue_head(p) (*(p)=0)
#define spin_lock_init(p) (*(p)=0)
struct bio {};
struct kfifo {int allocated;};
struct kcompress {void *kcompressd;int kcompressd_wait;struct kfifo write_fifo;int write_fifo_lock,running;};
struct kcompressd_para {int *kcompressd_wait;struct kfifo *write_fifo;int *running;};
struct write_work {void *mem;struct bio *bio;void (*cb)(void *,struct bio *);};
struct config_kcompressed {int enable;};
struct proc_dir_entry {int dummy;};
static int enable_kcompressd,allocations,alloc_calls,fail_alloc,fifos,fail_fifo,threads,fail_thread,procs,disabled;
static unsigned int nr_kcompressd,queue_size_per_kcompressd;
static struct kcompress *kcompress;static struct kcompressd_para *kcompressd_para;
static struct proc_dir_entry *kcompress_proc,proc_entry;
static const char *module_name_kcompressed="kcompressed";
static struct config_kcompressed config={1};
static void *kvcalloc(size_t n,size_t sz,int flags) {(void)flags;if(++alloc_calls==fail_alloc)return NULL;void *p=calloc(n,sz);assert(p);allocations++;return p;}
static void kvfree(void *p) {if(p){free(p);assert(allocations>0);allocations--;}}
static int kfifo_alloc(struct kfifo *f,unsigned int n,int flags) {(void)n;(void)flags;if(fail_fifo)return -ENOMEM;f->allocated=1;fifos++;return 0;}
static void kfifo_free(struct kfifo *f) {assert(f->allocated);f->allocated=0;fifos--;}
static unsigned int kfifo_out(struct kfifo *f,void *p,unsigned int n) {(void)f;(void)p;(void)n;return 0;}
static void bio_put(struct bio *p) {(void)p;abort();}
static void *start_thread(void) {if(fail_thread)return (void*)(intptr_t)-EAGAIN;threads++;return malloc(1);}
#define kthread_run(...) start_thread()
static void kthread_stop(void *p) {assert(threads>0);threads--;free(p);}
static int oplus_test_mm_feature_disable(int n) {(void)n;return disabled;}
static void *oplus_read_mm_config(const char *name) {(void)name;return &config;}
static struct proc_dir_entry *proc_mkdir(const char *name,void *p) {(void)name;(void)p;return NULL;}
static struct proc_dir_entry *create_proc(void) {procs++;return &proc_entry;}
#define proc_create_single(...) create_proc()
static void proc_remove(struct proc_dir_entry *p) {if(p){assert(procs>0);procs--;}}
void kcompressd_exit(void);
/* CASES */
int main(void)
{
 for(int test=0;test<6;test++) {
  alloc_calls=0;fail_alloc=test==0?1:test==1?2:0;fail_fifo=test==2;fail_thread=test==3;disabled=test==5;
  int result=kcompressd_init();
  if(test<4)assert(result<0);else assert(!result);
  if(test==4)assert(enable_kcompressd&&threads==1&&fifos==1&&procs==1);
  kcompressd_exit();
  assert(!enable_kcompressd&&!allocations&&!fifos&&!threads&&!procs&&!kcompress&&!kcompressd_para&&!kcompress_proc);
 }
 puts("PASS actual kcompress init/exit: two allocation failures, FIFO failure, thread failure, success and disabled configuration");
 return 0;
}
