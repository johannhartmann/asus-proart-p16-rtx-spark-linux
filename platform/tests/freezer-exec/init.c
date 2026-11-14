// SPDX-License-Identifier: GPL-2.0-only
#define _GNU_SOURCE
#include <sys/mount.h>
#include <sys/reboot.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
static pid_t kids[16];
static int control(const char *path,const char *value) {
 int fd=open(path,O_WRONLY|O_CLOEXEC);if(fd<0)return -errno;
 ssize_t n=write(fd,value,strlen(value));int rc=n==(ssize_t)strlen(value)?0:-(n<0?errno:EIO);close(fd);return rc;
}
static bool contains(const char *path,const char *needle) {
 char buf[8192]={0};int fd=open(path,O_RDONLY|O_CLOEXEC);if(fd<0)return false;
 ssize_t n=read(fd,buf,sizeof(buf)-1);close(fd);return n>0 && strstr(buf,needle);
}
static bool prefreeze(void) {
 if(control("/sys/fs/cgroup/stress/cgroup.freeze","1\n"))return false;
 for(unsigned n=0;n<500;n++){if(contains("/sys/fs/cgroup/stress/cgroup.events","frozen 1"))return true;usleep(10000);}
 return false;
}
int main(void) {
 int result=1;unsigned raw_fail=0,raw_ok=0,group_ok=0;setvbuf(stdout,NULL,_IONBF,0);
 mount("devtmpfs","/dev","devtmpfs",0,NULL);mkdir("/sys",0755);mkdir("/proc",0755);
 mount("sysfs","/sys","sysfs",0,NULL);mount("proc","/proc","proc",0,NULL);
 /* Never admit this controller on the workstation or outside guest PID 1. */
 if(getpid()!=1 || !contains("/sys/class/dmi/id/sys_vendor","QEMU"))return 42;
 if(!contains("/sys/power/pm_test","freezer"))goto out;
 mkdir("/sys/fs/cgroup",0755);
 if(mount("none","/sys/fs/cgroup","cgroup2",0,NULL))goto out;
 if(mkdir("/sys/fs/cgroup/stress",0755))goto out;
 if(control("/sys/power/pm_freeze_timeout","1500\n"))goto out;
 if(control("/sys/module/suspend/parameters/pm_test_delay","0\n"))goto out;
 for(unsigned i=0;i<16;i++) {
  int gate[2];if(pipe(gate))goto out;kids[i]=fork();if(kids[i]<0)goto out;
  if(!kids[i]){char ch;close(gate[1]);if(read(gate[0],&ch,1)!=1)_exit(5);close(gate[0]);execl("/stress","stress",NULL);_exit(6);}
  close(gate[0]);char pid[32];snprintf(pid,sizeof(pid),"%d\n",kids[i]);
  if(control("/sys/fs/cgroup/stress/cgroup.procs",pid))goto out;
  if(write(gate[1],"x",1)!=1)goto out;
  close(gate[1]);
 }
 usleep(100000);
 if(control("/sys/power/pm_test","freezer\n"))goto out;
 for(unsigned i=0;i<12;i++) {
  int rc=control("/sys/power/state","mem\n");printf("RAW_FREEZER cycle=%u rc=%d\n",i,rc);
  if(!rc)raw_ok++;else if(rc==-EBUSY)raw_fail++;else goto out;
  usleep(10000);
 }
 for(unsigned i=0;i<12;i++) {
  if(!prefreeze()){puts("CGROUP_PREFREEZE_FAILED");goto out;}
  int rc=control("/sys/power/state","mem\n");printf("GROUP_FREEZER cycle=%u rc=%d\n",i,rc);
  if(control("/sys/fs/cgroup/stress/cgroup.freeze","0\n"))goto out;
  if(rc)goto out;
  group_ok++;usleep(10000);
 }
 printf("FREEZER_EXEC_RESULT raw_ok=%u raw_busy=%u prefrozen_ok=%u\n",raw_ok,raw_fail,group_ok);
 result=0;
out:
 control("/sys/fs/cgroup/stress/cgroup.freeze","0\n");control("/sys/power/pm_test","none\n");
 for(unsigned i=0;i<16;i++)if(kids[i]>0)kill(kids[i],SIGKILL);
 for(unsigned i=0;i<16;i++)if(kids[i]>0)waitpid(kids[i],NULL,0);
 printf("FREEZER_VM_EXIT result=%d\n",result);sync();reboot(RB_POWER_OFF);return result;
}
