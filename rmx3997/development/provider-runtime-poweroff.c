/* Guest-only shutdown: Android BusyBox poweroff requires Android property init. */
#include <fcntl.h>
#include <string.h>
#include <sys/reboot.h>
#include <unistd.h>
int main(void)
{
    char command[8192] = {0};
    int fd = open("/proc/cmdline", O_RDONLY);
    if (getuid() || fd < 0) return 1;
    ssize_t n = read(fd, command, sizeof(command)-1);
    close(fd);
    if (n <= 0 || !strstr(command, " rmx3997.provider_guest=1 ")) return 1;
    sync();
    return reboot(RB_POWER_OFF);
}
