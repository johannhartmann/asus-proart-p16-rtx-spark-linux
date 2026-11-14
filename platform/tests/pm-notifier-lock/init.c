// SPDX-License-Identifier: GPL-2.0-only
#define _GNU_SOURCE
#include <sys/mount.h>
#include <sys/reboot.h>
#include <sys/syscall.h>
#include <errno.h>
#include <fcntl.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#ifndef RETAIN_GATE
#error "Build separately with RETAIN_GATE=0 or RETAIN_GATE=1"
#endif
#ifndef MODEL_PARAMETERS
#if RETAIN_GATE
#define MODEL_PARAMETERS "run_test=1 retain_gate=1"
#else
#define MODEL_PARAMETERS "run_test=1 retain_gate=0"
#endif
#endif
#ifndef PM_EXPECT_ERROR
#define PM_EXPECT_ERROR 0
#endif

static bool contains(const char *path, const char *needle)
{
	char buf[8192] = {0};
	int fd = open(path, O_RDONLY | O_CLOEXEC);
	ssize_t n;

	if (fd < 0)
		return false;
	n = read(fd, buf, sizeof(buf) - 1);
	close(fd);
	return n > 0 && strstr(buf, needle);
}

static int control(const char *path, const char *value)
{
	int fd = open(path, O_WRONLY | O_CLOEXEC);
	ssize_t n;
	int rc;

	if (fd < 0)
		return -errno;
	n = write(fd, value, strlen(value));
	rc = n == (ssize_t)strlen(value) ? 0 : -(n < 0 ? errno : EIO);
	close(fd);
	return rc;
}

int main(void)
{
	int result = 1, fd, pm_rc = -1;
	bool selected = false;

	if (getpid() != 1)
		return 42;
	setvbuf(stdout, NULL, _IONBF, 0);
	if (mount("devtmpfs", "/dev", "devtmpfs", 0, NULL) ||
	    mount("sysfs", "/sys", "sysfs", 0, NULL) ||
	    mount("proc", "/proc", "proc", 0, NULL))
		return 43;
	if (!contains("/sys/class/dmi/id/sys_vendor", "QEMU"))
		return 44;
	fd = open("/model.ko", O_RDONLY | O_CLOEXEC);
	if (fd < 0)
		goto out;
	int loaded = syscall(SYS_finit_module, fd, MODEL_PARAMETERS, 0);
	close(fd);
	if (loaded)
		goto out;
	if (control("/sys/module/suspend/parameters/pm_test_delay", "0\n") ||
	    control("/sys/power/pm_test", "freezer\n"))
		goto out;
	selected = true;
	if (!contains("/sys/power/pm_test", "[freezer]"))
		goto out;
	pm_rc = control("/sys/power/state", "mem\n");
	if ((pm_rc != 0) == PM_EXPECT_ERROR)
		result = 0;
out:
	if (selected && control("/sys/power/pm_test", "none\n"))
		result = 1;
	printf("PM_NOTIFIER_VM_RESULT retain=%d pm_rc=%d result=%d\n",
		RETAIN_GATE, pm_rc, result);
	sync();
	reboot(RB_POWER_OFF);
	return result;
}
