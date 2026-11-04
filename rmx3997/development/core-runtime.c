#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/fs.h>
#include <linux/fanotify.h>
#include <linux/ipc.h>
#include <linux/ntsync.h>
#include <linux/sem.h>
#include <linux/shm.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/mount.h>
#include <sys/reboot.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/sysmacros.h>
#include <sys/utsname.h>
#include <sys/vfs.h>
#include <sys/wait.h>
#include <unistd.h>

/* Only the disposable QEMU guest executes this program. */
static int failures;
static void result(const char *name, int pass)
{
    printf("CORE_TEST %s=%s errno=%d\n", name, pass ? "PASS" : "FAIL", errno);
    failures += !pass;
}
static int text(const char *path, char *buf, size_t size)
{
    int fd = open(path, O_RDONLY);
    if (fd < 0) return -1;
    ssize_t n = read(fd, buf, size - 1);
    close(fd);
    if (n < 0) return -1;
    buf[n] = 0;
    return 0;
}
static int put(const char *path, const void *buf, size_t size)
{
    int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0600);
    if (fd < 0) return -1;
    ssize_t n = write(fd, buf, size);
    close(fd);
    return n == (ssize_t)size ? 0 : -1;
}
static int mount_checked(const char *kind, const char *path, long magic)
{
    if (!mount(kind, path, kind, 0, NULL)) return 0;
    struct statfs s;
    return errno == EBUSY && !statfs(path, &s) && s.f_type == magic ? 0 : -1;
}
static int child_ok(pid_t pid)
{
    int status = 0;
    return pid > 0 && waitpid(pid, &status, 0) == pid &&
           WIFEXITED(status) && WEXITSTATUS(status) == 0;
}
static int storage(void)
{
    char buf[128]; unsigned maj = 0, min = 0;
    /* QMP independently verifies this controller's vendor/device identity. */
    if (put("/sys/bus/pci/drivers/ufshcd/new_id", "1b36 0013\n", 10)) return -1;
    for (int i = 0; i < 300; i++) {
        if (!access("/sys/class/block/sda/dev", R_OK)) break;
        usleep(100000);
    }
    if (text("/sys/class/block/sda/dev", buf, sizeof(buf)) ||
        sscanf(buf, "%u:%u", &maj, &min) != 2) return -1;
    if (mknod("/dev/sda", S_IFBLK | 0600, makedev(maj, min))) return -1;
    mkdir("/dev/block", 0755); mkdir("/dev/block/by-name", 0755);
    if (symlink("/dev/sda", "/dev/block/by-name/userdata")) return -1;
    int fd = open("/dev/sda", O_RDONLY); uint64_t bytes = 0;
    int pass = fd >= 0 && !ioctl(fd, BLKGETSIZE64, &bytes) && bytes == 536870912;
    if (fd >= 0) close(fd);
    if (!pass || mount("/dev/sda", "/data", "ext4", 0, NULL)) return -1;
    if (text("/data/FIXTURE_ID", buf, sizeof(buf)) ||
        strcmp(buf, "RMX3997-CORE-DISPOSABLE-20261104\n")) return -1;
    printf("CORE_STORAGE sda=%u:%u bytes=%llu identity=%s", maj, min,
           (unsigned long long)bytes, buf);
    return 0;
}
static void ntsync_test(void)
{
    char buf[80]; unsigned maj, min;
    int pass = !text("/sys/class/misc/ntsync/dev", buf, sizeof(buf)) &&
               sscanf(buf, "%u:%u", &maj, &min) == 2;
    if (pass) pass = !mknod("/dev/ntsync", S_IFCHR | 0600, makedev(maj, min));
    int dev = pass ? open("/dev/ntsync", O_RDWR) : -1;
    struct ntsync_sem_args a = { .count = 1, .max = 2 };
    int sem = dev >= 0 ? ioctl(dev, NTSYNC_IOC_CREATE_SEM, &a) : -1;
    pass = sem >= 0 && !ioctl(sem, NTSYNC_IOC_SEM_READ, &a) && a.count == 1 && a.max == 2;
    uint32_t count = 1;
    pass = pass && !ioctl(sem, NTSYNC_IOC_SEM_RELEASE, &count) && count == 1 &&
           !ioctl(sem, NTSYNC_IOC_SEM_READ, &a) && a.count == 2;
    count = 1; errno = 0;
    pass = pass && ioctl(sem, NTSYNC_IOC_SEM_RELEASE, &count) == -1 && errno == EOVERFLOW;
    result("ntsync_semaphore_read_release_overflow", pass);
    if (sem >= 0) close(sem);
    if (dev >= 0) close(dev);
}
struct nm_payload {
    uint64_t magic; uint32_t cmd, uid; int32_t status;
    uint32_t arg, size; char buffer[4068];
} __attribute__((packed));
struct nm_rule {
    uint32_t flags, uid, uid_end, deny_start, deny_end;
    uint16_t virtual_len, real_len;
} __attribute__((packed));
static int nomount_cmd(struct nm_payload *p)
{
    uintptr_t address = (uintptr_t)p;
    p->magic = 0x4e4f4d4f554e54ULL; p->status = -999;
    errno = 0;
    long n = syscall(SYS_add_key, "nomount", "core-fixture", &address, sizeof(address), -2);
    return n == -1 && errno == ECANCELED && p->status == 0;
}
static void nomount_test(void)
{
    struct nm_payload *p = mmap(NULL, 4096, PROT_READ | PROT_WRITE,
                                MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (p == MAP_FAILED) { result("nomount_protocol", 0); return; }
    memset(p, 0, 4096); p->cmd = 1;
    int pass = nomount_cmd(p) && p->size == 2 && !memcmp(p->buffer, "22", 2);
    result("nomount_protocol_version", pass);
    const char *original = "/data/original", *replacement = "/data/replacement";
    pass = !put(original, "ORIGINAL", 8) && !put(replacement, "REPLACED", 8);
    memset(p, 0, 4096); p->cmd = 2;
    struct nm_rule h = { .virtual_len = strlen(original), .real_len = strlen(replacement) };
    memcpy(p->buffer, &h, sizeof(h));
    memcpy(p->buffer + sizeof(h), original, h.virtual_len);
    memcpy(p->buffer + sizeof(h) + h.virtual_len, replacement, h.real_len);
    p->size = sizeof(h) + h.virtual_len + h.real_len;
    pass = pass && nomount_cmd(p);
    char buf[64];
    pass = pass && !text(original, buf, sizeof(buf)) && !strcmp(buf, "REPLACED");
    result("nomount_actual_file_redirection", pass);
    memset(p, 0, 4096); p->cmd = 7;
    pass = nomount_cmd(p) && !text(original, buf, sizeof(buf)) && !strcmp(buf, "ORIGINAL");
    result("nomount_rule_revocation", pass);
    munmap(p, 4096);
}
static void namespace_test(void)
{
    pid_t child = fork();
    if (!child) _exit(unshare(CLONE_NEWIPC | CLONE_NEWNS | CLONE_NEWPID) ? 1 : 0);
    result("ipc_mount_pid_namespace_creation", child_ok(child));
    child = fork();
    if (!child) _exit(unshare(CLONE_NEWUSER) ? 1 : 0);
    result("user_namespace_creation", child_ok(child));
}
static int limited_fanotify_groups(void)
{
    int one = syscall(SYS_fanotify_init, FAN_CLOEXEC | FAN_REPORT_FID, O_RDONLY);
    errno = 0;
    int two = syscall(SYS_fanotify_init, FAN_CLOEXEC | FAN_REPORT_FID, O_RDONLY);
    int limited = two < 0 && errno == EMFILE;
    if (two >= 0) close(two);
    if (one >= 0) close(one);
    int again = syscall(SYS_fanotify_init, FAN_CLOEXEC | FAN_REPORT_FID, O_RDONLY);
    if (again >= 0) close(again);
    return one >= 0 && limited && again >= 0;
}
static void fanotify_test(void)
{
    char groups[64], marks[64];
    int ready = !text("/proc/sys/fs/fanotify/max_user_groups", groups, sizeof(groups)) &&
                !text("/proc/sys/fs/fanotify/max_user_marks", marks, sizeof(marks));
    ready = ready && !put("/proc/sys/fs/fanotify/max_user_groups", "1\n", 2) &&
            !put("/proc/sys/fs/fanotify/max_user_marks", "1\n", 2);
    result("fanotify_limit_sysctls", ready);
    if (!ready) return;
    result("fanotify_static_ucount_limit_release", limited_fanotify_groups());
    pid_t child = fork();
    if (!child) {
        if (setgid(10002) || setuid(10002)) _exit(2);
        _exit(limited_fanotify_groups() ? 0 : 1);
    }
    result("fanotify_dynamic_uid_ucount_limit_release", child_ok(child));
    child = fork();
    if (!child) {
        if (unshare(CLONE_NEWUSER)) _exit(2);
        _exit(limited_fanotify_groups() ? 0 : 1);
    }
    result("fanotify_nested_userns_limit_rollback", child_ok(child));
    int fd = syscall(SYS_fanotify_init, FAN_CLOEXEC, O_RDONLY);
    int pass = fd >= 0 && !put("/data/fanotify-a", "A", 1) && !put("/data/fanotify-b", "B", 1);
    pass = pass && !syscall(SYS_fanotify_mark, fd, FAN_MARK_ADD, (uint64_t)FAN_OPEN,
                            AT_FDCWD, "/data/fanotify-a");
    errno = 0;
    pass = pass && syscall(SYS_fanotify_mark, fd, FAN_MARK_ADD, (uint64_t)FAN_OPEN,
                           AT_FDCWD, "/data/fanotify-b") == -1 && errno == ENOSPC;
    if (fd >= 0) close(fd);
    result("fanotify_mark_limit_accounting", pass);
    result("fanotify_restore_limits",
           !put("/proc/sys/fs/fanotify/max_user_groups", groups, strlen(groups)) &&
           !put("/proc/sys/fs/fanotify/max_user_marks", marks, strlen(marks)));
}
static void sysvipc_test(void)
{
    int sem = syscall(SYS_semget, IPC_PRIVATE, 1, IPC_CREAT | 0600);
    pid_t child = sem >= 0 ? fork() : -1;
    if (!child) {
        struct sembuf op = { .sem_num = 0, .sem_op = 1, .sem_flg = SEM_UNDO };
        _exit(syscall(SYS_semop, sem, &op, 1) ? 1 : 0);
    }
    int pass = child_ok(child) && syscall(SYS_semctl, sem, 0, GETVAL, 0UL) == 0;
    if (sem >= 0) syscall(SYS_semctl, sem, 0, IPC_RMID, 0UL);
    result("sysvipc_sem_undo_on_child_exit", pass);
    int shm = syscall(SYS_shmget, IPC_PRIVATE, 4096, IPC_CREAT | 0600);
    char *mem = shm >= 0 ? (void *)syscall(SYS_shmat, shm, NULL, 0) : (void *)-1;
    child = -1;
    if (mem != (void *)-1) { strcpy(mem, "PARENT"); child = fork(); }
    if (!child) { strcpy(mem, "CHILD"); _exit(syscall(SYS_shmdt, mem) ? 1 : 0); }
    pass = child_ok(child) && !strcmp(mem, "CHILD");
    if (mem != (void *)-1) pass = !syscall(SYS_shmdt, mem) && pass;
    if (shm >= 0) syscall(SYS_shmctl, shm, IPC_RMID, NULL);
    result("sysvipc_shm_fork_detach_integrity", pass);
}
struct ksu_info { uint32_t version, flags, features, uapi; };
static int root_child(uid_t uid)
{
    int fds[2]; if (pipe(fds)) return -1;
    pid_t p = fork();
    if (!p) {
        close(fds[1]); dup2(fds[0], 0); close(fds[0]);
        if (setgid(uid) || setuid(uid)) { perror("fixture setuid"); _exit(126); }
        execl("/data/app/~~fixture/org.bakasu.bakasu-fixture/lib/arm64/libksud.so",
              "libksud.so", "debug", "su", NULL);
        perror("fixture exec libksud"); _exit(127);
    }
    close(fds[0]);
    const char *cmd = "/busybox id; [ $(/busybox id -u) = 0 ] || exit 1; echo CORE_BAKASU_UID0; exit 0\n";
    write(fds[1], cmd, strlen(cmd)); close(fds[1]);
    return child_ok(p);
}
static void root_test(void)
{
    int fd = -1;
    syscall(SYS_reboot, 0xdeadbeef, 0xcafebabe, 0, &fd);
    struct ksu_info info = {0};
    int pass = fd >= 0 && !ioctl(fd, _IOR('K', 2, struct ksu_info), &info);
    printf("CORE_BAKASU version=%u flags=%x uapi=%u\n", info.version, info.flags, info.uapi);
    result("bakasu_builtin_identity", pass && info.version == 35257 && !(info.flags & 1) && info.uapi == 6);
    char modules[16384];
    result("bakasu_lkm_not_loaded", !text("/proc/modules", modules, sizeof(modules)) &&
           !strstr(modules, "kernelsu "));
    if (pass) {
        uint32_t event = 1;
        pass = !ioctl(fd, _IOC(_IOC_WRITE, 'K', 3, 0), &event);
        result("bakasu_post_fs_event", pass);
        sleep(2);
        result("bakasu_untrusted_uid_denied", root_child(10001) == 0);
        result("bakasu_signed_manager_uid_granted", root_child(10000) == 1);
    } else result("bakasu_manager_root", 0);
    if (fd >= 0) close(fd);
}
int main(void)
{
    setvbuf(stdout, NULL, _IONBF, 0); setvbuf(stderr, NULL, _IONBF, 0);
    setenv("PATH", "/system/bin:/system/xbin", 1);
    struct utsname u; uname(&u);
    printf("CORE_UNAME %s %s\n", u.release, u.machine);
    if (getpid() != 1 || mount_checked("proc", "/proc", 0x9fa0) ||
        mount_checked("sysfs", "/sys", 0x62656572)) failures++;
    result("dedicated_ufs_storage", !failures && !storage());
    if (!failures) {
        fanotify_test(); sysvipc_test(); ntsync_test(); nomount_test();
        namespace_test(); root_test();
    }
    char *buf = malloc(2097152); long n = syscall(SYS_syslog, 3, buf, 2097152);
    puts("CORE_KERNEL_LOG_BEGIN"); if (n > 0) fwrite(buf, 1, n, stdout);
    puts("\nCORE_KERNEL_LOG_END");
    printf("CORE_RUNTIME_RESULT=%s\n", failures ? "FAIL" : "PASS");
    sync(); reboot(RB_POWER_OFF); for (;;) pause();
}
