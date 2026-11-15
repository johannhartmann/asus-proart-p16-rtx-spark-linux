#define _GNU_SOURCE
#include <sys/mount.h>
#include <sys/reboot.h>
#include <sys/syscall.h>
#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>
#include <errno.h>
#ifndef MODEL_PARAMETERS
#error model parameters required
#endif
int main(void)
{
	if (getpid() != 1) return 20;
	setvbuf(stdout, NULL, _IONBF, 0);
	mount("devtmpfs", "/dev", "devtmpfs", 0, NULL);
	int fd = open("/model.ko", O_RDONLY);
	if (fd < 0) return 10;
	errno = 0;
	int rc = syscall(SYS_finit_module, fd, MODEL_PARAMETERS, 0);
	int error = errno;
	close(fd);
	printf("BUS_CLASS_VM_LOAD rc=%d errno=%d\n", rc, error);
	if (rc) return 11;
	puts("BUS_CLASS_VM_PASS");
	sync(); reboot(RB_POWER_OFF); return 12;
}
