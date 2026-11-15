// SPDX-License-Identifier: GPL-2.0-only
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/klog.h>
#include <sys/mount.h>
#include <sys/reboot.h>
#include <sys/syscall.h>
#include <sys/utsname.h>
#include <unistd.h>
#ifndef EXPECT_LEGACY
#error EXPECT_LEGACY required
#endif
static int load(const char *name,const char *args) {
 int fd=open(name,O_RDONLY);if(fd<0){perror(name);return -1;}
 errno=0;int ret=syscall(SYS_finit_module,fd,args,0);int err=errno;close(fd);
 printf("SDHCI_VM_LOAD %s ret=%d errno=%d\n",name,ret,err);return ret;
}
static int present(void) {
 DIR *d=opendir("/sys/bus/pci/drivers/sdhci-pci");if(!d)return 0;
 struct dirent *e;int found=0;
 while((e=readdir(d))){unsigned a,b,c,f;if(sscanf(e->d_name,"%x:%x:%x.%x",&a,&b,&c,&f)==4)found++;}
 closedir(d);return found;
}
static int lockdep(void) {
 FILE *f=fopen("/proc/lockdep_stats","r");if(!f)return -1;
 char text[16384];size_t n=fread(text,1,sizeof(text)-1,f);fclose(f);text[n]=0;
 char *p=strstr(text,"debug_locks:");return p?atoi(strchr(p,':')+1):-1;
}
int main(void) {
 if(getpid()!=1)return 20;
 setvbuf(stdout,NULL,_IONBF,0);
 mount("devtmpfs","/dev","devtmpfs",0,NULL);mount("proc","/proc","proc",0,NULL);mount("sysfs","/sys","sysfs",0,NULL);
 struct utsname u;if(uname(&u))return 21;printf("SDHCI_VM_KERNEL %s legacy=%d\n",u.release,EXPECT_LEGACY);
 printf("SDHCI_VM_LOCKDEP_BEFORE=%d\n",lockdep());if(lockdep()!=1)return 31;
 const char *modules[]={"/cqhci.ko","/sdhci.ko","/sdhci-uhs2.ko","/sdhci-pci.ko"};
 for(unsigned i=0;i<sizeof(modules)/sizeof(*modules);i++)if(load(modules[i],""))return 22;
 if(present()!=1)return 23;
 if(load("/model.ko","run_test=1"))return 24;
 /* QMP hot-removes the bridge only after the host sees this marker. */
 puts("SDHCI_VM_READY_FOR_HOTREMOVE");
 for(int n=0;n<300 && present();n++)usleep(100000);
 if(present())return 25;
 usleep(500000);
 char *log=calloc(1,2*1024*1024);if(!log)return 26;
 int len=klogctl(3,log,2*1024*1024-1);if(len<0)return 27;
 int double_free=strstr(log,"Trying to free already-free IRQ")!=NULL;
 int circular=strstr(log,"possible circular locking dependency")!=NULL;
 printf("SDHCI_VM_RESULT duplicate_irq_free=%d circular_lock=%d expected_legacy=%d\n",double_free,circular,EXPECT_LEGACY);
 if(double_free!=EXPECT_LEGACY || circular!=EXPECT_LEGACY)return 28;
 if(strstr(log,"BUG:")||strstr(log,"Oops:"))return 29;
 unsigned warnings=0;for(char *p=log;(p=strstr(p,"WARNING:"));p++)warnings++;
 if(warnings!=(EXPECT_LEGACY?2u:0u))return 29;
 printf("SDHCI_VM_LOCKDEP_AFTER=%d\n",lockdep());if(lockdep()!=(EXPECT_LEGACY?0:1))return 32;
 puts("SDHCI_VM_PASS");free(log);sync();reboot(RB_POWER_OFF);return 30;
}
