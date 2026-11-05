/* SPDX-License-Identifier: GPL-2.0-only */
/* Host ownership/codec fixture; NOT kernel locking, hardware or UFS proof. */
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <limits.h>
#include <lz4.h>
#include <zstd.h>
typedef uint32_t u32; typedef uint64_t u64;
typedef long atomic64_t;
#define CONFIG_HYBRIDSWAP_CORE 1
#define PAGE_SIZE 4096U
#define PAGE_SHIFT 12
#define BITS_PER_LONG 64
#define CRYPTO_MAX_ALG_NAME 64
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define BUILD_BUG_ON(x) _Static_assert(!(x), #x)
#define IS_ERR(x) ((uintptr_t)(x) > (uintptr_t)-4096)
#define PTR_ERR(x) ((int)(intptr_t)(x))
#define ERR_PTR(x) ((void *)(intptr_t)(x))
#define GFP_KERNEL 0
#define GFP_NOWAIT 0
#define GFP_NOIO 0
#define __GFP_NOWARN 0
#define __GFP_HIGHMEM 0
#define __GFP_MOVABLE 0
#define __GFP_CMA 0
#define __GFP_KSWAPD_RECLAIM 0
#define ZS_MM_RO 0
#define ZS_MM_WO 1
#define likely(x) (x)
#define unlikely(x) (x)
#define WARN_ON(x) (!!(x))
#define WARN_ON_ONCE(x) (!!(x))
#define pr_err(...) ((void)0)
#define pr_info(...) ((void)0)
#define log_err(...) ((void)0)
#define scnprintf snprintf
#define DEVICE_ATTR_RW(x)
#define DEVICE_ATTR_WO(x)
#define ZRAM_FLAG_SHIFT 24
#define ZRAM_CODEC_SHIFT 40
#define ZRAM_MAX_COMPS 4
#define ZRAM_CODEC_MASK (3UL << ZRAM_CODEC_SHIFT)
enum zram_pageflags { ZRAM_LOCK=24,ZRAM_SAME,ZRAM_WB,ZRAM_UNDER_WB,
 ZRAM_HUGE,ZRAM_IDLE,ZRAM_BATCHING_OUT,ZRAM_FROM_HYBRIDSWAP,ZRAM_MCGID_CLEAR,ZRAM_IN_BD,__NR_ZRAM_PAGEFLAGS };
struct zram_table_entry { unsigned long handle, flags; };
struct zcomp_strm { void *buffer; int tfm; };
struct zcomp { struct zcomp_strm stream; };
struct page { unsigned char bytes[PAGE_SIZE]; };
struct bio {}; struct bio_vec { struct page *bv_page; unsigned long bv_len; unsigned int bv_offset; };
struct zram_stats { atomic64_t compr_data_size, same_pages, huge_pages, huge_pages_since, pages_stored, writestall; };
struct fake_disk { void *part0; };
struct hybridswap { unsigned int nr_objs; long ext_stored_pages[8]; };
struct zram { struct zram_table_entry *table; void *mem_pool; struct zcomp *comp;
 struct fake_disk *disk; int init_lock; unsigned long limit_pages; struct zram_stats stats;
 u64 disksize; char compressor[64]; struct hybridswap *hs_swap;
 struct zcomp *secondary[3]; char secondary_name[3][64]; };
struct device { struct zram *zram; }; struct device_attribute {};
struct fake_hybs { struct zram *zram; long zram_stored_size, hybridswap_stored_size, hybridswap_stored_pages; };
struct mem_cgroup { struct fake_hybs *hybs; struct {int id;} id; };
struct io_extent {struct mem_cgroup *mcg;int ext_id;};
struct hybridswap_stat { long zram_stored_size,stored_size,stored_pages,batchout_pages,batchout_real_load; };
static struct fake_hybs hybs; static struct mem_cgroup memcg={&hybs,{1}};
static struct hybridswap_stat hstat;
#define MEMCGRP_ITEM_DATA(m) ((m)->hybs)
#define MEMCGRP_ITEM(m,item) ((m)->hybs->item)
static int live_contexts, streams, slot_locked, fail_alloc, fail_codec, create_fail_at, creates;
static int core_enabled=1, mapped, live_handles;
static size_t huge_class_size=3800;
static unsigned long update_peak;
static int fail_kmalloc;
static void atomic64_add(long d,long *x) {*x+=d;}
static void atomic64_sub(long d,long *x) {*x-=d;}
static void atomic64_inc(long *x) {++*x;}
static void atomic64_dec(long *x) {--*x;}
#define atomic_inc atomic64_inc
#define atomic_dec atomic64_dec
static void rcu_read_lock(void) {} static void rcu_read_unlock(void) {}
static int hybridswap_core_enabled(void) {return core_enabled;}
static struct hybridswap_stat *hybridswap_get_stat_obj(void) {return &hstat;}
static struct mem_cgroup *zram_get_memcg(struct zram *z,u32 i) {(void)z;(void)i;return &memcg;}
static void zram_set_memcg(struct zram *z,u32 i,int id) {(void)z;(void)i;(void)id;}
static void zram_rmap_insert(struct zram *z,u32 i) {(void)z;(void)i;}
static void zram_rmap_erase(struct zram *z,u32 i) {(void)z;(void)i;}
static int zram_test_overwrite(struct zram *z,u32 i,int id) {(void)z;(void)i;(void)id;return 0;}
#define esentry_extid(e) ((e)>>15)
static void down_read(int *l) {assert(*l>=0);++*l;}
static void up_read(int *l) {assert(*l>0);--*l;}
static void down_write(int *l) {assert(!*l);*l=-1;}
static void up_write(int *l) {assert(*l==-1);*l=0;}
#define init_done(z) ((z)->disksize)
#define dev_to_zram(d) ((d)->zram)
static void zram_slot_lock(struct zram *z,u32 i) {(void)z;(void)i;assert(!slot_locked);slot_locked=1;}
static void zram_slot_unlock(struct zram *z,u32 i) {(void)z;(void)i;assert(slot_locked);assert(!streams&&!mapped);slot_locked=0;}
#define zram_get_handle(z,i) ((z)->table[i].handle)
#define zram_set_handle(z,i,h) ((z)->table[i].handle=(h))
#define zram_get_element(z,i) zram_get_handle(z,i)
#define zram_set_element(z,i,e) zram_set_handle(z,i,e)
#define zram_test_flag(z,i,f) ((z)->table[i].flags & (1UL<<(f)))
#define zram_set_flag(z,i,f) ((z)->table[i].flags |= (1UL<<(f)))
#define zram_clear_flag(z,i,f) ((z)->table[i].flags &= ~(1UL<<(f)))
#define zram_get_obj_size(z,i) ((z)->table[i].flags & ((1UL<<24)-1))
#define zram_set_obj_size(z,i,n) ((z)->table[i].flags=((z)->table[i].flags & ~((1UL<<24)-1)) | (n))
static struct zcomp *zcomp_create(const char *name) {assert(!streams);if(++creates==create_fail_at)return ERR_PTR(-ENOMEM);
 struct zcomp *c=calloc(1,sizeof(*c));assert(c);c->stream.buffer=malloc(PAGE_SIZE*2);assert(c->stream.buffer);
 c->stream.tfm=!strcmp(name,"zstd");live_contexts++;return c;}
static void zcomp_destroy(struct zcomp *c) {assert(c&&!streams&&!mapped);free(c->stream.buffer);free(c);live_contexts--;}
static struct zcomp_strm *zcomp_stream_get(struct zcomp *c) {assert(c&&!streams);streams=1;return &c->stream;}
static void zcomp_stream_put(struct zcomp *c) {(void)c;assert(streams);streams=0;}
static int zcomp_compress(struct zcomp_strm *s,const void *p,unsigned int *n) {if(fail_codec)return -EIO;
 if(s->tfm){size_t t=ZSTD_compress(s->buffer,PAGE_SIZE*2,p,PAGE_SIZE,3);if(ZSTD_isError(t))return -EIO;*n=t;}
 else {*n=LZ4_compress_default(p,s->buffer,PAGE_SIZE,PAGE_SIZE*2);if(!*n)return -EIO;}return 0;}
static int zcomp_decompress(struct zcomp_strm *s,const void *p,unsigned int n,void *dst) {if(fail_codec)return -EIO;
 if(s->tfm){size_t t=ZSTD_decompress(dst,PAGE_SIZE,p,n);return !ZSTD_isError(t)&&t==PAGE_SIZE?0:-EIO;}
 return LZ4_decompress_safe(p,dst,n,PAGE_SIZE)==PAGE_SIZE?0:-EIO;}
struct object {unsigned int size;unsigned char data[PAGE_SIZE*2];};
static unsigned long zs_malloc(void *p,unsigned int n,int gfp) {(void)p;(void)gfp;if(fail_alloc){--fail_alloc;return 0;}
 struct object *o=calloc(1,sizeof(*o));assert(o);o->size=n;live_handles++;return (unsigned long)o;}
static void zs_free(void *p,unsigned long h) {(void)p;if(h){assert(!mapped);free((void*)h);live_handles--;}}
static void *zs_map_object(void *p,unsigned long h,int mode) {(void)p;(void)mode;assert(h&&!mapped);mapped=1;return ((struct object*)h)->data;}
static void zs_unmap_object(void *p,unsigned long h) {(void)p;(void)h;assert(mapped);mapped=0;}
static unsigned long zs_get_total_pages(void *p) {(void)p;return live_handles;}
static void update_used_max(struct zram *z,unsigned long n) {(void)z;if(n>update_peak)update_peak=n;}
static void zram_lru_del(struct zram *z,u32 i) {long n=zram_get_obj_size(z,i);hybs.zram_stored_size-=n;hstat.zram_stored_size-=n;}
static void zram_lru_add_tail(struct zram *z,u32 i,struct mem_cgroup *m) {(void)m;long n=zram_get_obj_size(z,i);hybs.zram_stored_size+=n;hstat.zram_stored_size+=n;}
static void zs_destroy_pool(void *p) {(void)p;assert(!live_handles);}
static void *kmap_atomic(struct page *p) {return p->bytes;} static void kunmap_atomic(void *p) {(void)p;}
static int page_same_filled(void *p,unsigned long *value) {unsigned long *b=p;*value=b[0];for(unsigned i=1;i<PAGE_SIZE/sizeof(long);i++)if(b[i]!=*value)return 0;return 1;}
static void zram_fill_page(void *p,unsigned int n,unsigned long value) {for(unsigned i=0;i<n/sizeof(long);i++)((unsigned long*)p)[i]=value;}
static void free_block_bdev(struct zram *z,unsigned long x) {(void)z;(void)x;}
static void hybridswap_untrack(struct zram *z,u32 i) {zram_clear_flag(z,i,ZRAM_FROM_HYBRIDSWAP);}
static void hybridswap_track(struct zram *z,u32 i,void *m) {(void)i;(void)m;hybs.zram=z;}
static void *page_memcg(struct page *p) {(void)p;return NULL;}
#define PageLocked(p) 1
static int hybridswap_fault_out(struct zram *z,u32 i) {(void)z;(void)i;return 0;}
static int read_from_bdev(struct zram *z,struct bio_vec *v,unsigned long h,struct bio *b,bool p) {(void)z;(void)v;(void)h;(void)b;(void)p;return -EIO;}
static void *kmalloc(size_t n,int gfp) {(void)gfp;return fail_kmalloc?NULL:malloc(n);}
static char *kstrdup(const char *s,int gfp) {(void)gfp;return fail_kmalloc?NULL:strdup(s);}
static void kfree(void *p) {free(p);} static void vfree(void *p) {free(p);}
static char *strim(char *s) {size_t n=strlen(s);while(n&&strchr(" \t\n",s[n-1]))s[--n]=0;while(*s&&strchr(" \t\n",*s))s++;return s;}
static int kstrtouint(const char *s,int base,unsigned int *n) {char *end;unsigned long v;if(!*s||*s=='-')return -EINVAL;errno=0;v=strtoul(s,&end,base);if(*end||errno||v>UINT_MAX)return -EINVAL;*n=v;return 0;}
static int zcomp_available_algorithm(const char *s) {return !strcmp(s,"zstd")||!strcmp(s,"lz4");}
static void cond_resched(void) {assert(!slot_locked&&!streams&&!mapped);}
static void set_capacity_and_notify(struct fake_disk *d,unsigned long n) {(void)d;(void)n;}
static void part_stat_set_all(void *p,int n) {(void)p;(void)n;}
static void reset_bdev(struct zram *z) {(void)z;} static void hybridswap_unbind(struct zram *z) {(void)z;}
