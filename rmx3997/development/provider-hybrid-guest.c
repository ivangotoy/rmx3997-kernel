/* Actual disposable-UFS transport/lifetime consumer; no host execution. */
#define main provider_codec_main
#include "../provider/tests/provider-guest.c"
#undef main
#include <sys/mount.h>
#include <sys/syscall.h>
#include <pthread.h>
static void put_control(const char *path,const char *text)
{
 int fd=open(path,O_WRONLY|O_CLOEXEC);assert(fd>=0);
 assert(write(fd,text,strlen(text))==(ssize_t)strlen(text));assert(!close(fd));
}
static unsigned long long stat_value(const char *name)
{
 char text[8192];unsigned long long v=0;
 read_text("/data/memcg/provider/memory.swap_stat",text,sizeof(text));
 char *p=strstr(text,name);assert(p);assert(sscanf(p+strlen(name),"%llu",&v)==1);
 printf("HYBRID_STAT %s %llu\n",name,v);return v;
}
static void *cold_reader(void *arg)
{
 int fd=*(int *)arg;
 for(int i=0;i<8;i++) cycle(fd,7,0);
 return NULL;
}
int main(void)
{
 setvbuf(stdout,NULL,_IONBF,0);
 char text[8192],pid[64];read_text("/proc/cmdline",text,sizeof(text));
 assert(!getuid()&&strstr(text," rmx3997.provider_guest=1 "));
 assert(!mkdir("/data/memcg",0700));
 assert(!mount("none","/data/memcg","cgroup",0,"memory"));
 assert(!mkdir("/data/memcg/provider",0700));
 snprintf(pid,sizeof(pid),"%d",getpid());put_control("/data/memcg/provider/tasks",pid);
 assert(!write_attr("comp_algorithm","lzo-rle"));
 assert(!write_attr("recomp_algorithm","algo=zstd priority=1"));
 assert(!write_attr("disksize","1048576"));
 assert(!write_attr("backing_dev","/dev/sdb"));
 assert(!write_attr("hybridswap_core_enable","1"));
 read_text("/sys/block/zram0/hybridswap_core_enable",text,sizeof(text));
 assert(strstr(text,"hybridswap enable"));
 int fd=open("/dev/zram0",O_RDWR|O_CLOEXEC);assert(fd>=0);
 cycle(fd,7,1);
 assert(!write_attr("recompress","type=all priority=1"));
 cycle(fd,7,0);
 assert(stat_value("zramOrignalSize:")>0);
 put_control("/data/memcg/provider/memory.force_swapout","100");
 assert(stat_value("eswapOutTotal:")>0);
 unsigned long long offloaded=stat_value("eswapOrignalSize:");assert(offloaded>0);
 cycle(fd,7,0);
 /* eswapInTotal counts explicit batch swap-in, not read faults. These
  * cold block reads exercise SCENE_FAULT_OUT and its pageInTotal counter. */
 assert(stat_value("pageInTotal:")>0);
 assert(stat_value("eswapOrignalSize:")<offloaded);
 pthread_t reader;assert(!pthread_create(&reader,NULL,cold_reader,&fd));
 for(int i=0;i<8;i++) {
  put_control("/data/memcg/provider/memory.force_swapout","100");
  assert(!write_attr("recompress","type=all priority=1"));
 }
 assert(!pthread_join(reader,NULL));
 assert(write_attr("reset","1")==-1&&errno==EBUSY);
 errno=0;assert(syscall(SYS_delete_module,"oplus_bsp_hybridswap_zram",O_NONBLOCK)==-1&&errno==EBUSY);
 assert(!close(fd));assert(!write_attr("reset","1"));
 puts("PASS real hybrid UFS secondary-codec transport/readback/concurrent reclaim/recompress/module pin/busy reset/final reset");
 return 0;
}
