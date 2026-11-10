#!/usr/bin/env python3
"""Run actual DSP PM callbacks with retained-state and transition faults."""
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    source = Path(sys.argv[1] if len(sys.argv) > 1 else
                  Path(__file__).with_name('n1x_adsp.c')).read_text()
    callbacks = source[source.index('static int n1x_adsp_runtime_suspend('):
                       source.index('static const struct dev_pm_ops n1x_adsp_pm')]
    inspect = source[source.index('static ssize_t inspect_show('):
                     source.index('static struct device_attribute dev_attr_inspect')]
    assert 'SYSTEM_SLEEP_PM_OPS(n1x_adsp_suspend, n1x_adsp_resume)' in source
    code = r'''
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <semaphore.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/types.h>
#include "n1x_sroot_client.h"
struct device {int unused;};
struct device_attribute {int unused;};
struct work_struct {int unused;};
struct target {unsigned dram_bytes;};
struct n1x_adsp {
 pthread_mutex_t lock;
 struct device *dev;
 bool published, sleep_prepared, sleep_suspended, sleep_irq_disabled;
 bool boot_ready, ipc_poisoned, primary_task_active, processing_active;
 bool component_registered, sleep_pcm, sleep_messages, sleep_draining, primary_running;
 void *pwrap, *primary_owner, *primary_sram, *processing_messages;
 uint8_t *mailbox, *shared;
 int power_error, error, sleep_error, irq;
 unsigned sleep_cycles;
 unsigned sleep_config_before[2], sleep_config_after[2];
 bool sleep_config_valid, sleep_config_checked;
 uint64_t dma;
 struct target *target;
 struct work_struct power_work;
 struct n1x_sroot_client_result_v2 loader;
 const struct n1x_sroot_client_sleep_ops *sleep_ops;
 struct n1x_sroot_client *sroot_client;
};
#define READ_ONCE(x) (x)
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define ADSP_OUT_STATUS 0x104
#define ADSP_CONFIG_OFFSET 0x3a0
#define CAP_SYS_RAWIO 17
#define PM_SUSPEND_TO_IDLE 1
#define lower_32_bits(x) ((uint32_t)(x))
static int pm_suspend_target_state;
static bool enable_retention_sleep;
static struct device dev;
static struct target target={16U<<20};
static uint8_t registers[0x400];
static struct n1x_adsp dsp = {.lock=PTHREAD_MUTEX_INITIALIZER};
static _Thread_local bool locked, signal_lock;
static sem_t entering;
static unsigned warnings, suspends, resumes, gets, pm_puts, reads, disables, enables, flushes;
static unsigned votes, wakes, runtime_suspends, runtime_resumes;
static int suspend_result, resume_result, get_result, vote_result, wake_result;
static bool privileged = true, tx_idle=true, pending, corrupted, corrupted_bytes, worker_fault, consumed_boot_config;
static void mutex_lock(pthread_mutex_t *lock)
{
 assert(lock==&dsp.lock && !locked);
 if(signal_lock) {signal_lock=false;assert(!sem_post(&entering));}
 assert(!pthread_mutex_lock(lock));locked=true;
}
static void mutex_unlock(pthread_mutex_t *lock)
{assert(lock==&dsp.lock && locked);locked=false;assert(!pthread_mutex_unlock(lock));}
static void *dev_get_drvdata(struct device *d) {assert(d==&dev);return &dsp;}
#define dev_warn_ratelimited(...) (warnings++)
#define dev_err(...) ((void)0)
#define dev_info(...) ((void)0)
static int atomic_read(int *v) {return *v;}
static int mtk_pwrap_dev_suspend(void *p, int flags)
{assert(p==&dsp && flags==(dsp.published?1:0));
 if(dsp.published) assert(locked && dsp.sleep_irq_disabled && flushes && (!dsp.primary_owner || dsp.component_registered));
 suspends++;return suspend_result;}
static int mtk_pwrap_dev_resume(void *p, int flags)
{assert(p==&dsp && flags==(dsp.published?1:0));
 if(dsp.published) assert(locked && dsp.sleep_irq_disabled && dsp.sleep_suspended);
 resumes++;return resume_result;}
static void disable_irq(int irq)
{assert(locked && irq==42 && !dsp.sleep_irq_disabled);disables++;}
static void enable_irq(int irq)
{assert(locked && irq==42 && !dsp.sleep_irq_disabled);enables++;}
static void flush_work(struct work_struct *work)
{assert(locked && dsp.sleep_irq_disabled && work==&dsp.power_work);flushes++;
 if(worker_fault)dsp.power_error=-EIO;}
static bool n1x_adsp_tx_idle(struct n1x_adsp *d)
{assert(d==&dsp && locked && dsp.sleep_irq_disabled);return tx_idle;}
static int client_suspend(struct n1x_sroot_client *c)
{assert(c==(void *)&dsp && dsp.sleep_suspended && dsp.sleep_irq_disabled && suspends);
 votes++;return vote_result;}
static int client_resume(struct n1x_sroot_client *c)
{assert(c==(void *)&dsp && locked && resumes && votes && !resume_result && !corrupted && !corrupted_bytes);
 wakes++;return wake_result;}
static const struct n1x_sroot_client_sleep_ops ops={.suspend=client_suspend,.resume=client_resume};
static bool capable(int capability) {assert(capability==CAP_SYS_RAWIO);return privileged;}
static int pm_runtime_resume_and_get(struct device *d)
{assert(d==&dev && locked && !dsp.sleep_prepared);gets++;return get_result;}
static void pm_runtime_mark_last_busy(struct device *d) {assert(d==&dev && locked);}
static void pm_runtime_put_autosuspend(struct device *d)
{assert(d==&dev && locked);pm_puts++;}
static uint32_t readl(const void *p)
{assert(p && locked);reads++;
 if(p==dsp.mailbox+ADSP_OUT_STATUS)return pending;
 if(p==dsp.shared+ADSP_CONFIG_OFFSET)return consumed_boot_config || (corrupted && resumes)?0:lower_32_bits(dsp.dma);
 if(p==dsp.shared+ADSP_CONFIG_OFFSET+8)return consumed_boot_config?0:target.dram_bytes-(unsigned)(corrupted_bytes && resumes);
 assert(0);return 0;}
static int sysfs_emit(char *buffer, const char *format, ...)
{assert(buffer && format && locked);return 1;}
static int pm_runtime_force_suspend(struct device *d)
{assert(d==&dev && !locked && !dsp.published);runtime_suspends++;return suspend_result;}
static int pm_runtime_force_resume(struct device *d)
{assert(d==&dev && !locked && !dsp.published);runtime_resumes++;return resume_result;}

struct mt8901_afe_sram_buffer;
static unsigned sram_votes,sram_wakes;
static bool afe_restored=true;
static int mt8901_afe_sram_suspend(struct mt8901_afe_sram_buffer *b)
{assert(b && locked && dsp.sleep_suspended && dsp.sleep_irq_disabled);sram_votes++;return 0;}
static int mt8901_afe_sram_resume(struct mt8901_afe_sram_buffer *b)
{assert(b && locked && dsp.sleep_suspended && dsp.sleep_irq_disabled);sram_wakes++;return afe_restored?0:-EHOSTDOWN;}
#define symbol_get(n) n
#define symbol_put(n) ((void)0)
''' + callbacks + inspect + r'''
static void reset(void)
{
 assert(!locked);
 /* Test teardown, not a production recovery operation. */
 memset((char *)&dsp+sizeof(dsp.lock),0,sizeof(dsp)-sizeof(dsp.lock));
 dsp.dev=&dev;dsp.pwrap=&dsp;dsp.mailbox=dsp.shared=registers;
 dsp.irq=42;dsp.dma=0xe0000000;dsp.target=&target;dsp.sleep_ops=&ops;dsp.sroot_client=(void *)&dsp;
 warnings=suspends=resumes=gets=pm_puts=reads=disables=enables=flushes=votes=wakes=0;
 runtime_suspends=runtime_resumes=0;
 suspend_result=resume_result=get_result=vote_result=wake_result=0;
 privileged=tx_idle=true;pending=corrupted=corrupted_bytes=worker_fault=consumed_boot_config=false;
 enable_retention_sleep=false;pm_suspend_target_state=PM_SUSPEND_TO_IDLE;
 sram_votes=sram_wakes=0;afe_restored=true;
}
static void healthy(void)
{reset();dsp.published=dsp.boot_ready=true;dsp.loader.accepted=dsp.loader.staging_released=1;
 enable_retention_sleep=true;}
static int sleep_cycle(void)
{
 int err=n1x_adsp_prepare(&dev);
 if(err) return err;
 err=n1x_adsp_suspend(&dev);
 if(!err) err=n1x_adsp_resume(&dev);
 n1x_adsp_complete(&dev);
 return err;
}
static void *prepare_thread(void *result)
{signal_lock=true;*(int *)result=n1x_adsp_prepare(&dev);return NULL;}
int main(void)
{
 reset();assert(!sleep_cycle() && runtime_suspends==1 && runtime_resumes==1 && !dsp.sleep_prepared);
 reset();suspend_result=-EIO;
 assert(sleep_cycle()==-EIO && runtime_suspends==1 && !runtime_resumes);
 reset();resume_result=-ETIMEDOUT;assert(sleep_cycle()==-ETIMEDOUT && !dsp.sleep_prepared);
 reset();assert(!n1x_adsp_runtime_suspend(&dev) && !n1x_adsp_runtime_resume(&dev));
 healthy();enable_retention_sleep=false;
 for(unsigned i=0;i<32;i++) assert(sleep_cycle()==-EOPNOTSUPP && !suspends && !disables);
 assert(warnings==32 && !dsp.sleep_prepared);
 assert(n1x_adsp_runtime_suspend(&dev)==-EBUSY && !suspends);
 healthy();pm_suspend_target_state=3;assert(sleep_cycle()==-EOPNOTSUPP && !disables);
 healthy();pm_suspend_target_state=0;assert(sleep_cycle()==-EOPNOTSUPP && !disables);
 for(unsigned f=0;f<7;f++) {
  healthy();switch(f){case 0:dsp.boot_ready=false;break;case 1:dsp.loader.accepted=false;break;
   case 2:dsp.loader.staging_released=false;break;case 3:dsp.error=-EIO;break;
   case 4:dsp.sleep_error=-EIO;break;case 5:dsp.ipc_poisoned=true;break;case 6:dsp.power_error=-EIO;break;}
  assert(sleep_cycle()==-ENOTRECOVERABLE && !disables && !dsp.sleep_prepared);
 }
 for(unsigned f=0;f<5;f++) {
  healthy();switch(f){case 0:dsp.primary_owner=&dsp;break;case 1:dsp.primary_task_active=true;break;
   case 2:dsp.processing_active=true;break;case 3:dsp.primary_sram=&dsp;break;
   case 4:dsp.processing_messages=&dsp;break;}
  assert(sleep_cycle()==-EBUSY && !disables && !dsp.sleep_prepared);
 }
 healthy();for(unsigned i=0;i<32;i++) {
  assert(!sleep_cycle() && dsp.sleep_cycles==i+1 && !dsp.sleep_suspended && !dsp.sleep_irq_disabled);
  assert(dsp.published && dsp.boot_ready && !dsp.error && !dsp.sleep_prepared);
 }
 assert(votes==32 && wakes==32 && enables==32 && !gets && !pm_puts);
 healthy();consumed_boot_config=true;
 for(unsigned i=0;i<32;i++) {
  assert(!sleep_cycle() && dsp.sleep_cycles==i+1 && !dsp.error);
  assert(dsp.sleep_config_valid && !dsp.sleep_config_before[0] && !dsp.sleep_config_after[0]);
  assert(!dsp.sleep_config_before[1] && !dsp.sleep_config_after[1]);
 }
 healthy();assert(!n1x_adsp_prepare(&dev));n1x_adsp_complete(&dev);
 assert(!dsp.sleep_prepared && !suspends && !disables); /* Another prepare fails. */
 healthy();assert(!n1x_adsp_prepare(&dev) && !n1x_adsp_suspend(&dev));
 assert(!n1x_adsp_resume(&dev));n1x_adsp_complete(&dev); /* Later device aborts suspend. */
 assert(dsp.sleep_cycles==1 && wakes==1 && enables==1);
 for(unsigned f=0;f<3;f++) {
  healthy();pending=f==0;tx_idle=f!=1;worker_fault=f==2;
  assert(sleep_cycle()==(f==2?-ENOTRECOVERABLE:-EBUSY) && !suspends && !votes);
  assert(disables==1 && enables==1 && !dsp.sleep_irq_disabled);
 }
 healthy();suspend_result=-EBUSY;
 assert(sleep_cycle()==-EBUSY && enables==1 && !votes && !dsp.error && !resumes);
 healthy();suspend_result=-ETIMEDOUT;
 assert(sleep_cycle()==-ETIMEDOUT && dsp.sleep_irq_disabled && !enables && !votes && !resumes);
 assert(dsp.error==-ETIMEDOUT && dsp.published); /* Unknown D3: no speculative D0. */
 healthy();vote_result=-EBUSY;
 assert(sleep_cycle()==-EBUSY && resumes==1 && enables==1 && !wakes && !dsp.error);
 healthy();vote_result=-EBUSY;resume_result=-ETIMEDOUT;
 assert(sleep_cycle()==-ETIMEDOUT && !enables && dsp.sleep_irq_disabled && dsp.error);

 healthy();dsp.component_registered=true;dsp.primary_task_active=dsp.processing_active=true;
 dsp.primary_owner=&dsp;dsp.primary_sram=(void *)1;dsp.processing_messages=(void *)2;
 assert(!sleep_cycle() && sram_votes==2 && sram_wakes==2 && !dsp.sleep_pcm && !dsp.sleep_messages);
 healthy();dsp.component_registered=true;dsp.primary_running=true;
 assert(sleep_cycle()==-EBUSY && !disables && !suspends); /* Missing ALSA stop. */
 healthy();dsp.component_registered=true;dsp.primary_sram=(void *)1;afe_restored=false;
 assert(sleep_cycle()==-EHOSTDOWN && sram_votes==1 && sram_wakes==1 && !resumes && !enables);
 healthy();resume_result=-ETIMEDOUT;
 assert(sleep_cycle()==-ETIMEDOUT && !wakes && !enables && dsp.error && dsp.sleep_suspended);
 healthy();wake_result=-EHOSTDOWN;
 assert(sleep_cycle()==-EHOSTDOWN && wakes==1 && !enables && dsp.error);
 healthy();corrupted=true;
 assert(sleep_cycle()==-EIO && !wakes && !enables && dsp.error && dsp.sleep_suspended);
 healthy();corrupted_bytes=true;
 assert(sleep_cycle()==-EIO && !wakes && !enables && dsp.sleep_config_checked && dsp.sleep_suspended);
 healthy();assert(!n1x_adsp_prepare(&dev) && !n1x_adsp_suspend(&dev));
 dsp.sleep_config_valid=false;
 assert(n1x_adsp_resume(&dev)==-EIO && !wakes && !enables && dsp.sleep_suspended);
 n1x_adsp_complete(&dev);
 reset();assert(!n1x_adsp_prepare(&dev) && dsp.sleep_prepared);
 char buffer[1024];assert(inspect_show(&dev,NULL,buffer)==-EBUSY && !gets && !reads);
 n1x_adsp_complete(&dev);assert(!dsp.sleep_prepared);
 get_result=-EIO;assert(inspect_show(&dev,NULL,buffer)==-EIO && gets==1 && !pm_puts && !reads);
 privileged=false;assert(inspect_show(&dev,NULL,buffer)==-EPERM && gets==1);
 privileged=true;dsp.published=true;assert(inspect_show(&dev,NULL,buffer)==-EBUSY && gets==1);
 reset();assert(!sem_init(&entering,0,0));
 for(unsigned i=0;i<32;i++) {
  pthread_t thread;int result=0;mutex_lock(&dsp.lock);dsp.published=false;
  assert(!pthread_create(&thread,NULL,prepare_thread,&result));
  while(sem_wait(&entering)) assert(errno==EINTR);
  dsp.published=true;mutex_unlock(&dsp.lock);assert(!pthread_join(thread,NULL));
  assert(result==-EOPNOTSUPP && !dsp.sleep_prepared && !suspends);
 }
 assert(!sem_destroy(&entering));
 puts("DSP PM: retained cycles, opt-in/mode gates, active stream rejection, IRQ/work drain, timeouts, rollback and contention: PASS");
}
'''
    with tempfile.TemporaryDirectory(prefix='n1x-adsp-pm-') as temporary:
        test, binary = Path(temporary) / 'pm.c', Path(temporary) / 'pm'
        test.write_text(code)
        subprocess.run(['cc', '-I'+str(Path(__file__).parent), '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        '-Wno-unused-parameter', '-fsanitize=address,undefined',
                        '-g', '-pthread', str(test), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=30)


if __name__ == '__main__':
    main()
