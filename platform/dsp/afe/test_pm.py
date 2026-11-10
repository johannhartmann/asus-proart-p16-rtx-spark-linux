#!/usr/bin/env python3
"""Test actual AFE SRAM PM and system-sleep rollback with power/retention faults."""
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).parent


def main():
    source = (HERE/'mt8901-afe-sram.c').read_text()
    state = source[source.index('/* PM callbacks run under the AFE device lock.') :]
    wrapper = '\n'.join(line for line in (HERE/'mt8901-afe-pm.h').read_text().splitlines()
                        if not line.startswith('#'))
    code = r'''
#include <assert.h>
#include <stdbool.h>
#include <errno.h>
#include <string.h>
#include <stdio.h>
struct device {int unused;};
struct mt8901_afe_sram_buffer {int prepare_error,irq_error,start_error,irq_stop_error;};
struct mt8901_afe_sram {unsigned users,retention_users,sleeping_users,bytes;
 unsigned char *snapshot,*base;bool sleep_prepared,sleep_saved;
 struct mt8901_afe_sram_buffer *memif[7];};
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
struct mt8901_afe_private {struct mt8901_afe_sram *sram;};
struct mtk_base_afe {struct mt8901_afe_private *platform_priv;};
static struct device dev;
static unsigned char image[128],memory[128];
static struct mt8901_afe_sram sram;
static struct mt8901_afe_private priv={&sram};
static struct mtk_base_afe afe={&priv};
static bool powered=true;
static unsigned saves,restores,suspends,resumes;
static int suspend_error,resume_error;
#define atomic_read(p) (*(p))
static void *dev_get_drvdata(struct device *d) {assert(d==&dev);return &afe;}
static void memcpy_fromio(void *to,const void *from,size_t bytes)
{assert(powered && to==image && from==memory && bytes==128);saves++;memcpy(to,from,bytes);}
static void memcpy_toio(void *to,const void *from,size_t bytes)
{assert(powered && to==memory && from==image && bytes==128 && sram.sleep_saved);restores++;memcpy(to,from,bytes);}
static void wmb(void) {assert(powered && restores);}
static int pm_runtime_force_suspend(struct device *d)
{assert(d==&dev && (!sram.users || sram.sleep_saved));suspends++;powered=false;return suspend_error;}
static int pm_runtime_force_resume(struct device *d)
{assert(d==&dev);resumes++;if(!resume_error)powered=true;return resume_error;}
''' + state + wrapper + r'''
static void reset(void)
{
 powered=true;saves=restores=suspends=resumes=0;suspend_error=resume_error=0;
 priv.sram=&sram;sram=(struct mt8901_afe_sram){.snapshot=image,.base=memory,.bytes=128};
 memset(image,0,sizeof(image));memset(memory,0xa5,sizeof(memory));
}
int main(void)
{
 reset();assert(!mt8901_afe_pm_prepare(&dev) && !mt8901_afe_pm_suspend(&dev));
 assert(!saves && !restores && suspends==1 && !powered);
 assert(!mt8901_afe_pm_resume(&dev));mt8901_afe_pm_complete(&dev);
 assert(powered && !sram.sleep_prepared && !restores);
 reset();priv.sram=NULL;assert(!mt8901_afe_pm_prepare(&dev));mt8901_afe_pm_complete(&dev);
 reset();sram.users=2;assert(mt8901_afe_pm_prepare(&dev)==-EBUSY && !sram.sleep_prepared);
 for(unsigned i=0;i<4;i++) {
  reset();struct mt8901_afe_sram_buffer b={0};sram.memif[0]=&b;
  switch(i){case 0:b.prepare_error=-EIO;break;case 1:b.irq_error=-EIO;break;
   case 2:b.start_error=-EIO;break;case 3:b.irq_stop_error=-EIO;break;}
  assert(mt8901_afe_pm_prepare(&dev)==-ENOTRECOVERABLE && !sram.sleep_prepared);
 }
 reset();sram.users=sram.retention_users=2;assert(!mt8901_afe_pm_prepare(&dev));
 sram.sleeping_users=1;assert(mt8901_afe_pm_suspend(&dev)==-EBUSY && !suspends && !saves);
 sram.sleeping_users=2;
 for(unsigned i=0;i<32;i++) {
  assert(!mt8901_afe_pm_suspend(&dev) && !powered && sram.sleep_saved);
  memset(memory,0x11,sizeof(memory));assert(!mt8901_afe_pm_resume(&dev));
  assert(powered && !sram.sleep_saved && !memcmp(image,memory,128));
  assert(sram.users==2 && sram.retention_users==2 && sram.sleeping_users==2);
 }
 assert(saves==32 && restores==32);mt8901_afe_pm_complete(&dev);assert(!sram.sleep_prepared);
 reset();sram.users=sram.retention_users=sram.sleeping_users=1;
 assert(!mt8901_afe_pm_prepare(&dev));suspend_error=-EIO;
 assert(mt8901_afe_pm_suspend(&dev)==-EIO && powered && !sram.sleep_saved && resumes==1 && restores==1);
 reset();sram.users=sram.retention_users=sram.sleeping_users=1;
 assert(!mt8901_afe_pm_prepare(&dev));resume_error=-ETIMEDOUT;
 assert(!mt8901_afe_pm_suspend(&dev) && mt8901_afe_pm_resume(&dev)==-ETIMEDOUT);
 assert(!powered && sram.sleep_saved && !restores);
 mt8901_afe_pm_complete(&dev);assert(mt8901_afe_pm_prepare(&dev)==-EBUSY);
 reset();sram.users=sram.retention_users=sram.sleeping_users=1;
 assert(!mt8901_afe_pm_prepare(&dev));suspend_error=-EIO;resume_error=-ETIMEDOUT;
 assert(mt8901_afe_pm_suspend(&dev)==-EIO && sram.sleep_saved && !powered && !restores);
 puts("AFE PM: 32 retained SRAM cycles, ordering, missing votes, aborted suspend rollback and failed restoration: PASS");
}
'''
    with tempfile.TemporaryDirectory(prefix='mt8901-afe-pm-') as tmp:
        test, binary = Path(tmp)/'test.c', Path(tmp)/'test'
        test.write_text(code)
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', str(test), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
