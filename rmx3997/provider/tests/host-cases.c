/* SPDX-License-Identifier: GPL-2.0-only */
static void init_fixture(struct zram *z, unsigned int pages)
{
 static struct fake_disk disk;
 static struct hybridswap hybrid;
 memset(z,0,sizeof(*z));z->table=calloc(pages,sizeof(*z->table));assert(z->table);
	z->disk=&disk;
 memset(&hybrid,0,sizeof(hybrid));hybrid.nr_objs=pages;
 z->disksize=pages*PAGE_SIZE;z->mem_pool=z;z->hs_swap=&hybrid;
 strcpy(z->compressor,"lz4");z->comp=zcomp_create(z->compressor);assert(!IS_ERR(z->comp));
 strcpy(z->secondary_name[0],"zstd");assert(!zram_secondary_create(z));
}
static void pattern(struct page *p,unsigned int seed)
{for(unsigned int i=0;i<PAGE_SIZE;i++)p->bytes[i]=(i%61+seed)%251;}
static void read_equal(struct zram *z,struct page *p)
{struct page out;assert(!__zram_bvec_read(z,&out,0,NULL,false));assert(!memcmp(p,&out,sizeof(out)));}
int main(void)
{
 unsigned int changed=0;
 for(unsigned int round=0;round<1000;round++) {
  struct zram z;struct page p;char scratch[PAGE_SIZE];struct bio_vec bv={&p,PAGE_SIZE,0};
  init_fixture(&z,1);pattern(&p,round%251);assert(!__zram_bvec_write(&z,&bv,0,NULL));read_equal(&z,&p);
  unsigned long original=z.table[0].handle;unsigned int old=zram_get_obj_size(&z,0);
  assert(!zram_get_priority(&z,0));hybs.zram=&z;hybs.zram_stored_size=hstat.zram_stored_size=old;
  /* Failure leaves both ownership and decoder unchanged. */
  fail_codec=1;assert(zram_recompress_one(&z,0,1,RECOMP_ALL,0,scratch)==-EIO);fail_codec=0;
  assert(z.table[0].handle==original&&!zram_get_priority(&z,0));read_equal(&z,&p);
  fail_alloc=1;int n=zram_recompress_one(&z,0,1,RECOMP_ALL,0,scratch);assert(n==-ENOMEM||n==0);fail_alloc=0;
  assert(z.table[0].handle==original&&z.stats.compr_data_size==old);
  for(unsigned int f=ZRAM_WB;f<=ZRAM_UNDER_WB;f++) {zram_set_flag(&z,0,f);assert(!zram_recompress_one(&z,0,1,RECOMP_ALL,0,scratch));zram_clear_flag(&z,0,f);}
  zram_set_flag(&z,0,ZRAM_BATCHING_OUT);assert(!zram_recompress_one(&z,0,1,RECOMP_ALL,0,scratch));zram_clear_flag(&z,0,ZRAM_BATCHING_OUT);
  assert(!zram_recompress_one(&z,0,1,RECOMP_IDLE,0,scratch));zram_set_flag(&z,0,ZRAM_IDLE);
  n=zram_recompress_one(&z,0,1,RECOMP_IDLE,0,scratch);assert(n>=0);changed+=n;
  if(n){assert(zram_get_priority(&z,0)==1);assert(zram_get_obj_size(&z,0)<old);assert(hybs.zram_stored_size==z.stats.compr_data_size);assert(hstat.zram_stored_size==hybs.zram_stored_size);}
  read_equal(&z,&p);assert(!zram_recompress_one(&z,0,1,RECOMP_ALL,0,scratch));
  /* Execute the actual OEM move/restore functions with host UFS bytes,
   * allocator and memcg/list shims. This is not real OEM UFS I/O. */
  unsigned int size=zram_get_obj_size(&z,0);unsigned long tag=z.table[0].flags&ZRAM_CODEC_MASK;
  unsigned char transport[PAGE_SIZE];memcpy(transport,((struct object*)z.table[0].handle)->data,size);
  zram_slot_lock(&z,0);zram_lru_del(&z,0);zram_set_flag(&z,0,ZRAM_UNDER_WB);
  move_to_hybridswap(&z,0,123,&memcg);assert(zram_test_flag(&z,0,ZRAM_WB));
  assert((z.table[0].flags&ZRAM_CODEC_MASK)==tag);zram_slot_unlock(&z,0);
  unsigned long restored=zs_malloc(z.mem_pool,size,0);memcpy(((struct object*)restored)->data,transport,size);
  struct io_extent extent={&memcg,0};__move_to_zram(&z,0,restored,&extent);
  assert(!zram_test_flag(&z,0,ZRAM_WB));assert((z.table[0].flags&ZRAM_CODEC_MASK)==tag);read_equal(&z,&p);
  if(n){struct zcomp *saved=z.secondary[0];z.secondary[0]=NULL;struct page out;assert(__zram_bvec_read(&z,&out,0,NULL,false)==-EIO);z.secondary[0]=saved;}
  /* Rewriting a secondary slot must return ownership to primary. */
  pattern(&p,(round+1)%251);assert(!__zram_bvec_write(&z,&bv,0,NULL));assert(!zram_get_priority(&z,0));read_equal(&z,&p);
  /* Same-filled writes and discard/reset must drop codec identity too. */
  memset(&p,0,sizeof(p));assert(!__zram_bvec_write(&z,&bv,0,NULL));assert(zram_test_flag(&z,0,ZRAM_SAME));read_equal(&z,&p);
  zram_reset_device(&z);assert(!z.table&&!z.comp&&!z.secondary[0]&&!z.init_lock);
  assert(!live_contexts&&!live_handles&&!streams&&!slot_locked&&!mapped);
 }
 assert(changed>0);
 /* Raw huge -> secondary compression, then parser/bounds/config lifetime. */
 struct zram z;struct page p;char scratch[PAGE_SIZE];init_fixture(&z,1);pattern(&p,1);
 zram_set_handle(&z,0,zs_malloc(z.mem_pool,PAGE_SIZE,0));memcpy(((struct object*)z.table[0].handle)->data,p.bytes,PAGE_SIZE);
 zram_set_obj_size(&z,0,PAGE_SIZE);zram_set_flag(&z,0,ZRAM_HUGE);z.stats.compr_data_size=PAGE_SIZE;z.stats.huge_pages=1;z.stats.pages_stored=1;
 assert(zram_recompress_one(&z,0,1,RECOMP_HUGE,0,scratch)==1);assert(!z.stats.huge_pages);read_equal(&z,&p);
 struct device dev={&z};
 assert(recomp_algorithm_store(&dev,NULL,"algo=zstd priority=1",20)==-EBUSY);
 const char *bad[]={"priority=4","priority=0","priority=-1","priority=1 priority=2","type=no","max_pages=0","threshold=4097",""};
 for(unsigned int i=0;i<ARRAY_SIZE(bad);i++)assert(recompress_store(&dev,NULL,bad[i],strlen(bad[i]))==-EINVAL);
 assert(recompress_store(&dev,NULL,"type=all priority=1",19)==19);
 zram_reset_device(&z);
 assert(recomp_algorithm_store(&dev,NULL,"algo=zstd priority=3",20)==20);
 assert(recomp_algorithm_store(&dev,NULL,"algo=missing priority=1",23)==-EINVAL);
 fail_kmalloc=1;assert(recompress_store(&dev,NULL,"type=all",8)==-ENOMEM);fail_kmalloc=0;
 /* Allocation failure after a previous secondary was created unwinds all. */
 memset(&z,0,sizeof(z));strcpy(z.secondary_name[0],"zstd");strcpy(z.secondary_name[1],"lz4");create_fail_at=creates+2;
 assert(zram_secondary_create(&z)==-ENOMEM);assert(!z.secondary[0]&&!z.secondary[1]&&!live_contexts);
 puts("PASS actual provider functions: 1000 codec/read/write/error/transport-shim/reset lifecycles; raw/same/parser/unwind cases");
 return 0;
}
