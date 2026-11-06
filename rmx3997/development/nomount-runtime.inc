/* Runs only inside the disposable, file-backed ext4 QEMU acceptance guest.
 * The exact pinned freestanding nm CLI drives rules; raw calls test framing. */
#include <dirent.h>
#include <stdarg.h>
#include <stddef.h>
#include <sys/xattr.h>
#include <sys/prctl.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <linux/capability.h>
struct nm_payload_test {
 uint64_t magic; uint32_t cmd, target_uid; int status;
 uint32_t arg1, data_size; char buffer[4068];
} __attribute__((packed));
struct nm_rule_test {uint32_t flags,uid,end,deny_start,deny_end;uint16_t vl,rl;} __attribute__((packed));
_Static_assert(sizeof(struct nm_payload_test)==4096,"paired payload size");
_Static_assert(offsetof(struct nm_payload_test,buffer)==28,"paired field offsets");
static struct nm_payload_test np __attribute__((aligned(4096)));
static long nm_raw(struct nm_payload_test *p) {
 uintptr_t ptr=(uintptr_t)p;
 return syscall(SYS_add_key,"nomount","trigger",&ptr,sizeof(ptr),-1);
}
static int nm_command(unsigned cmd, unsigned arg) {
 memset(&np,0,sizeof(np));np.magic=0x4E4F4D4F554E54ULL;np.cmd=cmd;np.target_uid=arg;np.status=-1234;
 errno=0;long rc=nm_raw(&np);
 return rc==-1 && errno==ECANCELED?np.status:-10000-errno;
}
static int nm_cli(const char *first, ...) {
 char *args[16];args[0]="/data/nm";args[1]=(char *)first;int n=2;
 va_list ap;va_start(ap,first);const char *a;
 while((a=va_arg(ap,const char *)) && n<15)args[n++]=(char *)a;
 va_end(ap);args[n]=NULL;
 pid_t p=fork();if(!p){execv(args[0],args);_exit(127);}return child_ok(p);
}
static int nm_rule(const char *v,const char *r) {return nm_cli("rule","add",v,r,NULL);}
static int nm_del(const char *v) {return nm_cli("rule","del",v,NULL);}
static int nm_read_is(const char *path,const char *want) {char b[256];return !text(path,b,sizeof(b)) && !strcmp(b,want);}
static int nm_listed_ino(const char *dir,const char *name,ino_t *ino) {
 DIR *d=opendir(dir);int count=0;if(!d)return -1;struct dirent *e;
 while((e=readdir(d)))if(!strcmp(e->d_name,name)){count++;if(ino)*ino=e->d_ino;}closedir(d);return count;
}
static int nm_listed(const char *dir,const char *name) {return nm_listed_ino(dir,name,NULL);}
static int nm_add_raw(const char *v,const char *r,unsigned flags) {
 memset(&np,0,sizeof(np));np.magic=0x4E4F4D4F554E54ULL;np.cmd=2;np.status=-1234;
 struct nm_rule_test h={.flags=flags,.vl=strlen(v),.rl=strlen(r)};
 memcpy(np.buffer,&h,sizeof(h));memcpy(np.buffer+sizeof(h),v,h.vl);memcpy(np.buffer+sizeof(h)+h.vl,r,h.rl);np.data_size=sizeof(h)+h.vl+h.rl;
 errno=0;long rc=nm_raw(&np);return rc==-1 && errno==ECANCELED?np.status:-10000-errno;
}
static void nomount_tests(void) {
 int start=failures;char domain[256]={0};text("/proc/self/attr/current",domain,sizeof(domain));printf("NOMOUNT_GUEST_DOMAIN=%s\n",domain);
 result("nomount_exact_pinned_cli_version",nm_cli("version",NULL) && !nm_command(1,0) && np.data_size==2 && !memcmp(np.buffer,"22",2));
 result("nomount_key_ecanceled_and_bad_command",nm_command(0xffff,0)==-EOPNOTSUPP);
 uintptr_t ptr=1;errno=0;long rc=syscall(SYS_add_key,"nomount","trigger",&ptr,sizeof(ptr),-1);
 result("nomount_bad_user_pointer_fails_closed",rc==-1 && errno==EFAULT);
 memset(&np,0,sizeof(np));np.magic=0x4E4F4D4F554E54ULL;np.cmd=2;np.data_size=sizeof(np.buffer)+1;np.status=-1234;rc=nm_raw(&np);
 int malformed=rc==-1 && errno==ECANCELED && np.status==-EINVAL;
 np.data_size=1;np.arg1=0;np.status=-1234;rc=nm_raw(&np);malformed=malformed && rc==-1 && errno==ECANCELED && np.status==-EINVAL;
 result("nomount_payload_bounds_and_truncated_rule",malformed);
 pid_t p=fork();if(!p){struct __user_cap_header_struct h={.version=_LINUX_CAPABILITY_VERSION_3};struct __user_cap_data_struct caps[2]={{0}};if(syscall(SYS_capget,&h,caps))_exit(1);caps[CAP_SYS_ADMIN/32].effective&=~(1U<<(CAP_SYS_ADMIN%32));if(syscall(SYS_capset,&h,caps))_exit(1);np.status=-1234;errno=0;long x=nm_raw(&np);_exit(x==-1 && errno==EPERM && np.status==-1234?0:1);}
 result("nomount_cap_sys_admin_denial",child_ok(p));
 p=fork();if(!p){struct sock_filter ins[]={BPF_STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(struct seccomp_data,nr)),BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,SYS_add_key,0,1),BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ERRNO|EACCES),BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ALLOW)};struct sock_fprog f={.len=4,.filter=ins};if(prctl(PR_SET_NO_NEW_PRIVS,1,0,0,0)||prctl(PR_SET_SECCOMP,SECCOMP_MODE_FILTER,&f))_exit(1);np.status=-1234;errno=0;long x=nm_raw(&np);_exit(x==-1 && errno==EACCES && np.status==-1234?0:1);}
 result("nomount_seccomp_denial_distinct_from_kernel_absence",child_ok(p));
 mkdir("/data/nmfixture",0777);chmod("/data/nmfixture",0777);mkdir("/data/nmfixture/view",0777);chmod("/data/nmfixture/view",0777);mkdir("/data/nmfixture/back",0777);
 const char *v="/data/nmfixture/view/native",*r="/data/nmfixture/back/real",*i="/data/nmfixture/view/injected";
 int ok=!put(v,"native",6) && !put(r,"redirect",8);chmod(v,0666);chmod(r,0666);chmod("/data/nmfixture/back",0755);
 ok=ok && !setxattr(r,"user.nomount","back",4,0);
 result("nomount_ext4_fixture_inputs",ok);
 if(!ok || failures!=start){result("nomount_prerequisites_abort",0);return;}
 result("nomount_native_and_injected_rule_cli",nm_rule(v,r) && nm_rule(i,r) && nm_cli("rule","list","--json",NULL));
 /* Change backing access after rule construction; synthetic metadata alone
  * must not authorize an open. Test actual ext4 ACL and DAC enforcement. */
 int dac=!chmod(r,0600);p=fork();if(!p){if(setresuid(12345,12345,12345))_exit(1);errno=0;int f=open(v,O_RDONLY);if(f>=0)close(f);_exit(f==-1 && errno==EACCES?0:1);}
 result("nomount_backing_dac_permission_enforced",dac && child_ok(p));chmod(r,0666);
 struct {uint32_t version;struct {uint16_t tag,perm;uint32_t id;} e[5];} acl={2,{{1,6,0xffffffffU},{2,0,12345},{4,4,0xffffffffU},{16,4,0xffffffffU},{32,4,0xffffffffU}}};
 int ac=!setxattr(r,"system.posix_acl_access",&acl,sizeof(acl),0);p=fork();if(!p){if(setresuid(12345,12345,12345))_exit(1);errno=0;int f=open(v,O_RDONLY);if(f>=0)close(f);_exit(f==-1 && errno==EACCES?0:1);}
 result("nomount_backing_posix_acl_permission_enforced",ac && child_ok(p));removexattr(r,"system.posix_acl_access");chmod(r,0666);
 struct stat st,rs,fdst;int fd=open(i,O_RDWR);char b[256]={0};
 ok=fd>=0 && !stat(i,&st) && !fstat(fd,&fdst) && !stat(r,&rs) && st.st_size==8 && st.st_mode==rs.st_mode && st.st_ino==fdst.st_ino && st.st_dev==rs.st_dev;
 result("nomount_lookup_open_stat_fstat_consistency",ok && nm_read_is(v,"redirect") && nm_read_is(i,"redirect"));
 result("nomount_readdir_each_name_once",nm_listed("/data/nmfixture/view","native")==1 && nm_listed("/data/nmfixture/view","injected")==1);
 int n=getxattr(i,"user.nomount",b,sizeof(b));ok=n==4 && !memcmp(b,"back",4) && !setxattr(i,"user.nomount","test",4,0);
 memset(b,0,sizeof(b));n=getxattr(r,"user.nomount",b,sizeof(b));ok=ok && n==4 && !memcmp(b,"test",4);n=listxattr(i,b,sizeof(b));ok=ok && n>0 && memmem(b,n,"user.nomount",12);
 result("nomount_xattr_get_set_list_backing_consistency",ok);
 ok=fd>=0 && pwrite(fd,"updated!",8,0)==8 && !fsync(fd) && nm_read_is(r,"updated!") && nm_read_is(v,"updated!");
 result("nomount_write_read_fsync_backing_consistency",ok);
 errno=0;int io=ioctl(fd,0xDEAD,b);int ie=errno;int pp[2];int sp=!pipe(pp);errno=0;ssize_t sr=sp?syscall(SYS_splice,fd,NULL,pp[1],NULL,1,0):0;int se=errno;if(sp){close(pp[0]);close(pp[1]);}
 result("nomount_unsupported_ioctl_splice_fail_closed",io==-1 && ie==EOPNOTSUPP && sp && sr==-1 && se==EOPNOTSUPP);
 char *map=fd>=0?mmap(NULL,4096,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0):MAP_FAILED;
 ok=map!=MAP_FAILED && !memcmp(map,"updated!",8);if(map!=MAP_FAILED){memcpy(map,"mapped!!",8);ok=ok && !msync(map,4096,MS_SYNC);}
 result("nomount_shared_mmap_write_uses_real_filesystem",ok && nm_read_is(r,"mapped!!"));
 result("nomount_uid_block_and_cache_revalidation",!nm_command(4,0) && nm_read_is(v,"native") && access(i,F_OK)==-1 && nm_listed("/data/nmfixture/view","injected")==0 && !nm_command(5,0) && nm_read_is(i,"mapped!!"));
 result("nomount_uid_clear_restores_selected_view",!nm_command(4,0) && nm_read_is(v,"native") && !nm_command(8,0) && nm_read_is(v,"mapped!!"));
 result("nomount_rule_remove_retains_open_fd_and_mapping",nm_del(i) && access(i,F_OK)==-1 && fd>=0 && pread(fd,b,8,0)==8 && !memcmp(b,"mapped!!",8) && map!=MAP_FAILED && !memcmp(map,"mapped!!",8));
 if(fd>=0)close(fd);if(map!=MAP_FAILED)munmap(map,4096);
 result("nomount_per_uid_cli_rule_selection",nm_cli("clear",NULL) && nm_cli("rule","add","--uid","12345",v,r,NULL) && nm_read_is(v,"native"));
 p=fork();if(!p){if(setresuid(12345,12345,12345))_exit(1);_exit(nm_read_is(v,"mapped!!")?0:1);}result("nomount_matching_uid_sees_redirect",child_ok(p));
 result("nomount_nonmatching_uid_cache_restored",nm_read_is(v,"native") && nm_cli("rule","del","--uid","12345",v,NULL) && nm_rule(v,r));
 /* Shared phase handshakes keep the reader alive for every actual mutation. */
 volatile int *phase=mmap(NULL,4096,PROT_READ|PROT_WRITE,MAP_SHARED|MAP_ANONYMOUS,-1,0);
 ok=phase!=MAP_FAILED;if(ok){phase[0]=0;phase[1]=0;}p=ok?fork():-1;
 if(!p){int good=1;for(int step=1;step<=40;step++){
   while(__atomic_load_n(&phase[0],__ATOMIC_ACQUIRE)<step){char buf[32]={0};int f=open(v,O_RDONLY);ssize_t n=f>=0?read(f,buf,sizeof(buf)-1):-1;if(f>=0)close(f);if(n<0 || (strcmp(buf,"native") && strcmp(buf,"mapped!!")))good=0;DIR *d=opendir("/data/nmfixture/view");if(!d)good=0;else{while(readdir(d)){}closedir(d);}}
   if(!nm_read_is(v,step%2?"native":"mapped!!"))good=0;
   __atomic_store_n(&phase[1],step,__ATOMIC_RELEASE);
 }_exit(good?0:1);}
 for(int step=1;ok && step<=40;step++){
   ok=step%2?!nm_command(7,0):nm_rule(v,r);
   __atomic_store_n(&phase[0],step,__ATOMIC_RELEASE);
   int waited=0;while(__atomic_load_n(&phase[1],__ATOMIC_ACQUIRE)<step && waited++<5000)usleep(1000);
   ok=ok && phase[1]==step;
 }
 if(!ok && p>0)kill(p,SIGKILL);
 result("nomount_concurrent_lookup_readdir_clear_readd",child_ok(p) && ok);
 if(phase!=MAP_FAILED)munmap((void *)phase,4096);
 errno=0;int blocked_link=link(v,"/data/nmfixture/unsafe-link");int le=errno;
 errno=0;int blocked_rename=rename(v,"/data/nmfixture/unsafe-rename");int re=errno;
 errno=0;int blocked_unlink=unlink(v);int ue=errno;
 result("nomount_synthetic_link_rename_unlink_fail_closed",blocked_link==-1 && le==EOPNOTSUPP && blocked_rename==-1 && re==EOPNOTSUPP && blocked_unlink==-1 && ue==EOPNOTSUPP && nm_read_is(v,"mapped!!"));
 result("nomount_clear_all_restores_native_and_removes_injection",!nm_command(6,0) && nm_read_is(v,"native") && access(i,F_OK)==-1);
 result("nomount_unsupported_directory_whiteout_crossfs_paths",nm_add_raw("/data/nmfixture/view/dir","/data/nmfixture/back",0)==-EOPNOTSUPP && nm_add_raw(v,r,4)==-EOPNOTSUPP && nm_add_raw("/proc/nm-rejected",r,0)==-EOPNOTSUPP && nm_add_raw(v,"/proc/version",0)==-EOPNOTSUPP && nm_add_raw("/data/nmfixture/view/../bad",r,0)==-EINVAL);
 result("nomount_unsupported_symlink_hardlink",!symlink(r,"/data/nmfixture/back/link") && nm_add_raw(v,"/data/nmfixture/back/link",0)==-EOPNOTSUPP && !link(r,"/data/nmfixture/back/hard") && nm_add_raw(v,r,0)==-EOPNOTSUPP && !unlink("/data/nmfixture/back/hard"));
 /* Wait for asynchronous retirement before unmount; never detach/bypass EBUSY. */
 sync();int unmounted=0;for(int j=0;j<100;j++){if(!umount("/data")){unmounted=1;break;}if(errno!=EBUSY)break;usleep(20000);}
 result("nomount_clear_reclaim_ext4_unmount",unmounted);
 result("nomount_ext4_remount_after_wrapper_destruction",unmounted && !mount("/dev/sda","/data","ext4",0,NULL) && nm_rule(v,r) && nm_read_is(v,"mapped!!") && nm_del(v) && nm_read_is(v,"native"));
 int rediscovery=1;for(int cycle=0;cycle<2;cycle++){
  ino_t ino=0;struct stat observed;rediscovery=rediscovery && !nm_command(7,0) && nm_rule(i,r) && !stat(i,&observed) && nm_listed_ino("/data/nmfixture/view","injected",&ino)==1 && ino==observed.st_ino && nm_read_is(i,"mapped!!") && nm_del(i) && access(i,F_OK)==-1 && nm_listed("/data/nmfixture/view","injected")==0;
 }
 result("nomount_single_injection_readd_readdir_stat_inode",rediscovery);
 int ro=!mount("/dev/sda","/data","ext4",MS_REMOUNT|MS_RDONLY,NULL);
 int rodenied=ro && nm_add_raw(v,r,0)==-EOPNOTSUPP;
 int rw=ro && !mount("/dev/sda","/data","ext4",MS_REMOUNT,NULL);
 result("nomount_readonly_ext4_admission_fails_closed",rodenied && rw && nm_rule(v,r) && nm_del(v));
 printf("NOMOUNT_RUNTIME_RESULT=%s\n",failures==start?"PASS":"FAIL");
}
