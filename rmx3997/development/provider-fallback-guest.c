/* Original-provider compatibility after candidate integrity rejection, guest only. */
#define main provider_codec_main
#include "../provider/tests/provider-guest.c"
#undef main
int main(void)
{
 char text[8192];read_text("/proc/cmdline",text,sizeof(text));
 assert(!getuid()&&strstr(text," rmx3997.provider_guest=1 "));
 assert(access("/sys/block/zram0/recomp_algorithm",F_OK)==-1&&errno==ENOENT);
 assert(!write_attr("comp_algorithm","lzo-rle"));
 assert(!write_attr("disksize","1048576"));
 int fd=open("/dev/zram0",O_RDWR|O_CLOEXEC);assert(fd>=0);
 cycle(fd,3,1);assert(compressed_bytes()>0);
 assert(write_attr("reset","1")==-1&&errno==EBUSY);
 assert(!close(fd));assert(!write_attr("reset","1"));
 puts("PASS real original provider fallback cold read/write/busy reset/final reset");
 return 0;
}
