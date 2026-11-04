#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/fs.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mount.h>
#include <sys/reboot.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/sysmacros.h>
#include <sys/utsname.h>
#include <sys/wait.h>
#include <unistd.h>

static int text(const char *path,char *buf,size_t len) {
 int fd=open(path,O_RDONLY);if(fd<0)return -1;ssize_t n=read(fd,buf,len-1);close(fd);
 if(n<0)return -1;buf[n]=0;buf[strcspn(buf,"\r\n")]=0;return 0;
}
static int block(const char *name,const char *serial,unsigned long long bytes,int ro) {
 char path[256],buf[256];unsigned int ma,mi;unsigned long long size=0;int readonly=-1;
 char found=0;
 for(char disk='a';disk<='c';disk++){
  snprintf(path,sizeof(path),"/sys/class/block/sd%c/device",disk);
  ssize_t n=readlink(path,buf,sizeof(buf)-1);
  if(n<=0)continue;buf[n]=0;
  char *last=strrchr(buf,'/');unsigned h,ch,id,lun;
  unsigned expected=!strcmp(serial,"RMX3997-AK3-BOOT")?0:!strcmp(serial,"RMX3997-AK3-INIT")?1:2;
  if(last&&sscanf(last+1,"%u:%u:%u:%u",&h,&ch,&id,&lun)==4&&lun==expected){found=disk;break;}
 }
 if(!found)return -1;
 snprintf(path,sizeof(path),"/sys/class/block/sd%c/dev",found);
 if(text(path,buf,sizeof(buf))||sscanf(buf,"%u:%u",&ma,&mi)!=2)return -1;
 snprintf(path,sizeof(path),"/dev/block/%s",name);
 if(mknod(path,S_IFBLK|0600,makedev(ma,mi)))return -1;
 int fd=open(path,O_RDONLY);if(fd<0)return -1;
 int bad=ioctl(fd,BLKGETSIZE64,&size)||ioctl(fd,BLKROGET,&readonly);close(fd);
 printf("RMX_NATIVE_BLOCK %s source=sd%c bytes=%llu readonly=%d serial=%s\n",name,found,size,readonly,serial);
 return bad||size!=bytes||readonly!=ro ? -1:0;
}
static int run(char *const argv[]) {
 pid_t pid=fork();if(pid<0)return -1;
 if(!pid){execv(argv[0],argv);perror("execv");_exit(127);}
 int status;if(waitpid(pid,&status,0)<0)return -1;
 return WIFEXITED(status)?WEXITSTATUS(status):128+WTERMSIG(status);
}
static void klog(void) {
 char *buf=malloc(2*1024*1024);puts("RMX_NATIVE_KERNEL_LOG_BEGIN");
 if(buf){long n=syscall(SYS_syslog,3,buf,2*1024*1024);if(n>0)fwrite(buf,1,n,stdout);free(buf);}
 puts("\nRMX_NATIVE_KERNEL_LOG_END");
}
int main(void) {
 int result=1, mounted=0;char buf[4096];struct utsname u;
 setvbuf(stdout,NULL,_IONBF,0);setvbuf(stderr,NULL,_IONBF,0);
 puts("RMX_NATIVE_INIT_BEGIN");
 if(getpid()!=1||getuid()!=0||uname(&u))goto done;
 printf("RMX_NATIVE_UNAME %s %s\n",u.release,u.machine);
 if(strncmp(u.release,"5.15.197-android13-8-",sizeof("5.15.197-android13-8-")-1)||strcmp(u.machine,"aarch64"))goto done;
 if(mount("proc","/proc","proc",0,NULL)||mount("sysfs","/sys","sysfs",0,NULL))goto done;
 syscall(SYS_syslog,8,NULL,1);
 if(text("/proc/cmdline",buf,sizeof(buf))||!strstr(buf,"rmx3997_ak3_native=1")||!strstr(buf,"androidboot.slot_suffix=_b"))goto done;
 int pci=open("/sys/bus/pci/drivers/ufshcd/new_id",O_WRONLY);
 if(pci<0||write(pci,"1b36 0013\n",10)!=10)goto done;close(pci);
 for(int i=0;i<300&&access("/sys/class/block/sdc/dev",R_OK);i++)usleep(100000);
 if(block("test_boot","RMX3997-AK3-BOOT",67108864,0)||block("test_init","RMX3997-AK3-INIT",8388608,1)||block("test_data","RMX3997-AK3-DATA",536870912,0))goto done;
 if(symlink("/dev/block/test_boot","/dev/block/by-name/boot_b")||symlink("/dev/block/test_init","/dev/block/by-name/init_boot_b"))goto done;
 if(symlink("/dev/block/test_data","/dev/block/by-name/userdata"))goto done;
 if(mount("/dev/block/test_data","/data","ext4",0,NULL))goto done;
 mounted=1;
 setenv("PATH","/system/bin:/system/xbin:/vendor/bin",1);
 setenv("LD_LIBRARY_PATH","/system/lib64",1);
 char *const preflight[]={"/busybox","sh","-c","/system/bin/toybox id; /system/bin/toybox stat -f -c %T /data; /system/bin/toybox unzip --help; /busybox --help",NULL};
 if(run(preflight))goto done;
 char *const entry[]={"/system/bin/sh","/entry","3","1","/package.zip",NULL};
 result=run(entry);printf("RMX_NATIVE_ENTRY_EXIT=%d\n",result);
 char *const verify[]={"/busybox","sh","-c","echo RMX_NATIVE_HASHES_BEGIN; /busybox sha256sum /dev/block/test_boot /dev/block/test_init; for f in /data/adb/rmx3997-ak3/work.*/boot_b.before.img; do echo RMX_NATIVE_BACKUP=$f; /busybox sha256sum \"$f\"; done; /busybox find /data/adb/rmx3997-ak3 -maxdepth 3 -type f; echo RMX_NATIVE_HASHES_END",NULL};
 if(run(verify))result=1;
done:
 printf("RMX_NATIVE_RESULT=%s errno=%d\n",result?"FAIL":"PASS",errno);
 klog();sync();if(mounted&&umount("/data"))printf("RMX_NATIVE_UMOUNT_ERROR=%d\n",errno);
 sync();reboot(RB_POWER_OFF);for(;;)pause();
}
