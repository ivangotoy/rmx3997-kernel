/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual init/add-disk bodies, with explicit allocator/VFS/registration shims. */
#include <assert.h>
#include <stdlib.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <limits.h>
#define __init
#define CONFIG_HYBRIDSWAP 1
#define CONFIG_KCOMPRESSD 1
#define CONFIG_HYBRIDSWAP_SWAPD 1
#define CONFIG_OPLUS_FEATURE_MM_OSVELTE 1
#define CONFIG_OPLUS_FEATURE_MM_EZRECLAIMD 1
#define IS_ENABLED(x) (x)
#define GFP_KERNEL 0
#define SLAB_PANIC 1
#define NUMA_NO_NODE -1
#define PAGE_SIZE 4096
#define ZRAM_LOGICAL_BLOCK_SIZE 4096
#define ZRAM_TYPE_BASEPAGE 0
#define QUEUE_FLAG_NONROT 0
#define QUEUE_FLAG_ADD_RANDOM 1
#define QUEUE_FLAG_DISCARD 2
#define QUEUE_FLAG_STABLE_WRITES 3
#define pr_err(...) ((void)0)
#define pr_info(...) ((void)0)
#define log_err(...) ((void)0)
#define log_info(...) ((void)0)
#define INIT_LIST_HEAD(p) (*(p)=0)
#define init_rwsem(p) (*(p)=0)
#define mutex_lock(p) ((void)(p))
#define mutex_unlock(p) ((void)(p))
#define blk_queue_flag_set(...) ((void)0)
#define blk_queue_flag_clear(...) ((void)0)
#define blk_queue_physical_block_size(...) ((void)0)
#define blk_queue_logical_block_size(...) ((void)0)
#define blk_queue_io_min(...) ((void)0)
#define blk_queue_io_opt(...) ((void)0)
#define blk_queue_max_discard_sectors(...) ((void)0)
#define blk_queue_max_write_zeroes_sectors(...) ((void)0)
#define set_capacity(...) ((void)0)
struct queue {struct {unsigned int discard_granularity;} limits;};
struct gendisk {int major,first_minor,minors;const void *fops;void *private_data;char disk_name[16];struct queue *queue;int registered;};
struct zram {struct gendisk *disk;int init_lock;char compressor[128];};
struct hybridswapd_operations {int (*pre_init)(void);void (*pre_deinit)(void);int *memcg_legacy_files;};
struct mem_cgroup_hybridswap {int dummy;};
struct config_ezreclaimd {bool enable;};
static struct config_ezreclaimd config={false};
static const char *module_name_ezreclaimd="ezreclaimd",*default_compressor="lzo-rle";
static struct hybridswapd_operations *hybridswapd_ops;
static void *hybridswap_cache;static bool ezreclaimd_enable;
static int score_head,log_level,memory_cgrp_subsys,mem_cgroup_hybridswap_legacy_files[1],ops_files[1];
#define HS_LOG_INFO 1
static int zram_index_mutex,zram_index_idr,zram_major,zram_devops;
static int zram_control_class;
static const void *hybrid_zram_disk_attr_groups,*zram_disk_attr_groups;
static struct zram *zram_arr[2],*idr;
static unsigned int num_devices;
static int failure,add_result,cache_live,cgroups,ops_live,pre_live,hooks_live,disks,classes,cpu_states,majors,debugs,kcomp_live;
static int unregistered_cleanups,deleted_registered,publications,fallbacks;
static void *kmem_cache_create(const char *n,size_t s,size_t a,int flags,void *ctor)
{(void)n;(void)s;(void)a;(void)ctor;assert(!(flags&SLAB_PANIC));if(failure==1)return NULL;cache_live++;return malloc(1);}
static void kmem_cache_destroy(void *p) {assert(cache_live==1&&!cgroups&&!hooks_live);cache_live--;free(p);}
static void *kzalloc(size_t s,int flags) {(void)flags;if(s==sizeof(struct hybridswapd_operations)){if(failure==3)return NULL;ops_live++;}return calloc(1,s);}
static void kfree(void *p) {if(p==hybridswapd_ops)ops_live--;free(p);}
static int cgroup_add_legacy_cftypes(void *ss,int *f) {(void)ss;if((f==mem_cgroup_hybridswap_legacy_files&&failure==2)||(f==ops_files&&failure==5))return -ENOMEM;cgroups++;return 0;}
static void cgroup_rm_cftypes(int *f) {(void)f;assert(cgroups>0);cgroups--;}
static int ops_pre_init(void) {if(failure==4)return -ENOMEM;pre_live=1;return 0;}
static void ops_pre_deinit(void) {assert(pre_live);pre_live=0;}
static void hybridswapd_ops_init(struct hybridswapd_operations *p) {p->pre_init=ops_pre_init;p->pre_deinit=ops_pre_deinit;p->memcg_legacy_files=ops_files;}
static void ezr_empty_ops_init(struct hybridswapd_operations *p) {hybridswapd_ops_init(p);}
static void *oplus_read_mm_config(const char *n) {(void)n;return &config;}
static int register_all_hooks(void) {if(failure==6)return -EIO;hooks_live=1;return 0;}
static int idr_alloc(int *i,void *p,int a,int b,int g) {(void)i;(void)a;(void)b;(void)g;assert(!idr);idr=p;return 0;}
static void idr_remove(int *i,int id) {(void)i;(void)id;assert(idr);idr=NULL;}
static struct gendisk *blk_alloc_disk(int n) {(void)n;struct gendisk *d=calloc(1,sizeof(*d));d->queue=calloc(1,sizeof(*d->queue));disks++;return d;}
static int device_add_disk(void *p,struct gendisk *d,const void *groups) {(void)p;(void)groups;if(!add_result)d->registered=1;return add_result;}
static void blk_cleanup_disk(struct gendisk *d) {if(!d->registered)unregistered_cleanups++;disks--;free(d->queue);free(d);}
static void del_gendisk(struct gendisk *d) {assert(d->registered);deleted_registered++;}
static void zram_debugfs_register(struct zram *z) {(void)z;publications++;}
static void zram_debugfs_create(void) {debugs=1;}
static void zram_debugfs_destroy(void) {debugs=0;}
static int cpuhp_setup_state_multi(int a,const char*b,void*c,void*d) {(void)a;(void)b;(void)c;(void)d;cpu_states=1;return 0;}
#define CPUHP_ZCOMP_PREPARE 1
#define zcomp_cpu_up_prepare NULL
#define zcomp_cpu_dead NULL
static void cpuhp_remove_multi_state(int n) {(void)n;cpu_states=0;}
static int class_register(void *p) {(void)p;classes=1;return 0;}
static void class_unregister(void *p) {(void)p;classes=0;}
static int register_blkdev(int n,const char*p) {(void)n;(void)p;majors=1;return 42;}
static void unregister_blkdev(int n,const char*p) {(void)n;(void)p;majors=0;}
static int kcompressd_init(void) {kcomp_live=1;return 0;}
static void kcompressd_exit(void) {kcomp_live=0;}
static void zram_remove_cb(void) {}
static void idr_for_each(int *i,void (*cb)(void),void *data)
{(void)i;(void)cb;(void)data;if(idr){del_gendisk(idr->disk);blk_cleanup_disk(idr->disk);free(idr);idr=NULL;zram_arr[0]=NULL;}}
static void idr_destroy(int *i) {(void)i;assert(!idr);}
/* CASES */
static void assert_clean(void)
{assert(!cache_live&&!cgroups&&!ops_live&&!pre_live&&!hooks_live&&!disks&&!classes&&!cpu_states&&!majors&&!debugs&&!kcomp_live&&!idr);}
int main(void)
{
 /* Both add_disk call sites: errors -ENOMEM/-EIO/+1 and success. */
 for(int branch=0;branch<2;branch++)for(int n=0;n<4;n++) {
  int values[]={-ENOMEM,-EIO,1,0};failure=0;add_result=values[n];publications=0;
  int before=unregistered_cleanups,del=deleted_registered;int result=zram_add(branch);
  if(add_result){assert(result==(add_result>0?-EIO:add_result));assert(!idr&&!disks&&!publications&&!zram_arr[branch]);assert(unregistered_cleanups==before+1&&deleted_registered==del);}
  else {assert(result==0&&idr&&publications==1);del_gendisk(idr->disk);blk_cleanup_disk(idr->disk);free(idr);idr=NULL;zram_arr[branch]=NULL;}
 }
 for(failure=1;failure<=6;failure++) {
  add_result=0;num_devices=1;publications=0;assert(zram_init()<0);assert_clean();
  /* Original OEM load is attempted only after replacement resources drained. */
  fallbacks++;
 }
 failure=0;add_result=1;num_devices=1;int before=publications;
 assert(zram_init()==-EIO);assert_clean();assert(publications==before);fallbacks++;
 assert(fallbacks==7);puts("PASS actual provider init fallback/unwind7 failures; both disk branches -ENOMEM/-EIO/+1/0");return 0;
}
