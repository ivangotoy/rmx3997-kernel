/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual provider consumer for the parent's disposable production-Image VM.
 * Never executes on a phone lacking the explicit guest-only command-line flag.
 * No scratch filesystem is created on ZRAM; it is solely the tested device.
 */
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define PAGE 4096
#define PAGES 128
static void read_text(const char *path, char *buf, size_t size)
{
 int fd=open(path,O_RDONLY|O_CLOEXEC);assert(fd>=0);
 ssize_t n=read(fd,buf,size-1);assert(n>=0);buf[n]=0;assert(!close(fd));
}
static int write_attr(const char *name,const char *value)
{
 char path[256];assert(snprintf(path,sizeof(path),"/sys/block/zram0/%s",name)<(int)sizeof(path));
 int fd=open(path,O_WRONLY|O_CLOEXEC|O_NOFOLLOW);if(fd<0)return -1;
 ssize_t n=write(fd,value,strlen(value));int saved=errno;close(fd);errno=saved;
 return n==(ssize_t)strlen(value)?0:-1;
}
static void pattern(unsigned char *buf,unsigned int page,unsigned int generation)
{
 uint32_t random=page+123+generation;
 for(unsigned int i=0;i<PAGE;i++) {
  random^=random<<13;random^=random>>17;random^=random<<5;
  buf[i]=page%4==0?0:page%4==1?(i%61+generation)%251:random;
 }
}
static void cycle(int fd,unsigned int generation,int writing)
{
 unsigned char expected[PAGE],actual[PAGE];
 if(writing) {
  for(unsigned int i=0;i<PAGES;i++) {
   pattern(expected,i,generation);
   assert(pwrite(fd,expected,PAGE,(off_t)i*PAGE)==PAGE);
  }
 }
 /* Buffered block I/O must reach the provider; warm page-cache readback is
  * insufficient evidence for codecs or post-recompression decoding. */
 assert(!fsync(fd));
 assert(!posix_fadvise(fd,0,0,POSIX_FADV_DONTNEED));
 for(unsigned int i=0;i<PAGES;i++) {
  pattern(expected,i,generation);
  assert(pread(fd,actual,PAGE,(off_t)i*PAGE)==PAGE);
  assert(!memcmp(expected,actual,PAGE));
 }
}
static unsigned long long compressed_bytes(void)
{
 char text[512];unsigned long long original,compressed;
 read_text("/sys/block/zram0/mm_stat",text,sizeof(text));
 assert(sscanf(text,"%llu %llu",&original,&compressed)==2);
 assert(original>0);return compressed;
}
int main(void)
{
 char command[8192],text[8192];struct stat st;
 read_text("/proc/cmdline",text,sizeof(text));
 assert(snprintf(command,sizeof(command)," %s ",text)<(int)sizeof(command));
 assert(strstr(command," rmx3997.provider_guest=1 "));
 assert(!getuid());
 FILE *swaps=fopen("/proc/swaps","r");assert(swaps);
 assert(fgets(text,sizeof(text),swaps));assert(!fgets(text,sizeof(text),swaps));fclose(swaps);
 read_text("/sys/block/zram0/initstate",text,sizeof(text));assert(!strcmp(text,"0\n"));
 assert(!stat("/dev/zram0",&st)&&S_ISBLK(st.st_mode));
 assert(!write_attr("comp_algorithm","lzo-rle"));
 assert(!write_attr("recomp_algorithm","algo=zstd priority=1"));
 assert(!write_attr("disksize","1048576"));
 int fd=open("/dev/zram0",O_RDWR|O_CLOEXEC);assert(fd>=0);
 cycle(fd,0,1);unsigned long long before=compressed_bytes();
 assert(write_attr("recomp_algorithm","algo=zstd priority=2")==-1&&errno==EBUSY);
 assert(write_attr("recompress","priority=4")==-1&&errno==EINVAL);
 assert(write_attr("recompress","type=bad")==-1&&errno==EINVAL);
 assert(!write_attr("idle","all"));
 assert(!write_attr("recompress","type=idle priority=1 max_pages=128"));
 cycle(fd,0,0);assert(compressed_bytes()<before);
 /* Rewrite mixed raw/same/compressed slots, then decode and recompress again. */
 cycle(fd,1,1);assert(!write_attr("recompress","type=all priority=1"));cycle(fd,1,0);
 assert(write_attr("reset","1")==-1&&errno==EBUSY);
 assert(!close(fd));assert(!write_attr("reset","1"));
 read_text("/sys/block/zram0/initstate",text,sizeof(text));assert(!strcmp(text,"0\n"));
 assert(!write_attr("recomp_algorithm","algo=zstd priority=1"));
 assert(!write_attr("disksize","1048576"));
 fd=open("/dev/zram0",O_RDWR|O_CLOEXEC);assert(fd>=0);
 cycle(fd,2,1);assert(!write_attr("recompress","type=all priority=1"));cycle(fd,2,0);
 assert(!close(fd));assert(!write_attr("reset","1"));
 puts("PASS real provider mixed codec/read/write/recompress/error/busy/reset/reinitialize checks");
 return 0;
}
