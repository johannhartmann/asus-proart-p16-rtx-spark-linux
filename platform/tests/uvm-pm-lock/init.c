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
static int contains(const char *path, const char *needle)
{
 char buf[256] = {0};
 int fd = open(path, O_RDONLY | O_CLOEXEC);
 if (fd < 0) return 0;
 ssize_t n = read(fd, buf, sizeof(buf)-1);
 close(fd);
 return n > 0 && strstr(buf, needle) != NULL;
}
int main(void)
{
 if (getpid() != 1) return 42;
 setvbuf(stdout, NULL, _IONBF, 0);
 if (mount("devtmpfs", "/dev", "devtmpfs", 0, NULL) ||
     mount("sysfs", "/sys", "sysfs", 0, NULL) ||
     mount("proc", "/proc", "proc", 0, NULL)) return 43;
 if (!contains("/sys/class/dmi/id/sys_vendor", "QEMU")) return 44;
 int fd = open("/model.ko", O_RDONLY | O_CLOEXEC);
 int result = fd < 0 ? -1 : syscall(SYS_finit_module, fd, MODEL_PARAMETERS, 0);
 if (fd >= 0) close(fd);
 printf("UVM_PM_INIT_RESULT result=%d\n", result);
 sync();
 reboot(RB_POWER_OFF);
 return result != 0;
}
