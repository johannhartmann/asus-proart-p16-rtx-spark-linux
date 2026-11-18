// SPDX-License-Identifier: GPL-2.0-only
#define _GNU_SOURCE
#include <sys/mount.h>
#include <sys/reboot.h>
#include <sys/syscall.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#ifndef MODEL_PARAMETERS
#error MODEL_PARAMETERS required
#endif

int main(void)
{
    int fd, ret;
    char vendor[32] = {0};

    if (getpid() != 1)
        return 42;
    setvbuf(stdout, NULL, _IONBF, 0);
    if (mount("devtmpfs", "/dev", "devtmpfs", 0, NULL) ||
        mount("sysfs", "/sys", "sysfs", 0, NULL) ||
        mount("proc", "/proc", "proc", 0, NULL))
        return 43;
    fd = open("/sys/class/dmi/id/sys_vendor", O_RDONLY | O_CLOEXEC);
    if (fd < 0 || read(fd, vendor, sizeof(vendor) - 1) < 4 ||
        !strstr(vendor, "QEMU"))
        return 44;
    close(fd);
    fd = open("/model.ko", O_RDONLY | O_CLOEXEC);
    ret = fd < 0 ? -1 : syscall(SYS_finit_module, fd, MODEL_PARAMETERS, 0);
    if (fd >= 0)
        close(fd);
    printf("N1X_MMU_NOTIFIER_INIT_RESULT result=%d\n", ret);
    sync();
    reboot(RB_POWER_OFF);
    return ret != 0;
}
