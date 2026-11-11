#!/usr/bin/env python3
"""Exercise actual DSP shutdown ordering, ownership and partial-cleanup faults."""
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent


def main():
    source = (HERE / 'n1x_adsp.c').read_text()
    start = source.index('static int n1x_adsp_shutdown(struct n1x_adsp *dsp, bool release)\n{')
    shutdown = source[start:source.index('static void n1x_adsp_remove(', start)]
    code = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "n1x_sroot_client.h"
struct device {int unused;};
struct target {unsigned dram_bytes;};
struct loader {bool accepted,staging_released;};
struct mt8901_afe_sram_buffer {int unused;};
struct n1x_adsp {
 int lock,irq,error,shutdown_error,power_work;uint32_t shutdown_completed;
 struct device *dev;struct target *target;struct loader loader;
 bool published,boot_ready,shutdown_attempted,shutdown_done,shutdown_power_off,shutdown_provider_retired;
 bool sleep_prepared,sleep_suspended,sleep_draining,sleep_irq_disabled;
 void *primary_owner,*pwrap,*dram,*processing_area;
 uint64_t dma;uint8_t *mailbox;
 struct mt8901_afe_sram_buffer *primary_sram,*processing_messages;
 const struct n1x_sroot_client_shutdown_ops *shutdown_ops;
 struct n1x_sroot_client *sroot_client;
};
static struct device device;
static struct target target={24U<<20};
static struct mt8901_afe_sram_buffer ring,messages;
static struct n1x_adsp dsp;
static uint8_t mailbox[512];
static unsigned symbols,disables,flushes,powers,releases,retires,frees,pm_puts,modules;
static unsigned admissions,release_attempts,pm_stages;
static bool locked;
static int missing,admit_error,power_error,release_error_at,retire_error,status_error;
#define THIS_MODULE ((void *)1)
#define PAGE_SIZE 4096
#define ADSP_OUT_STATUS 0x104
#define WRITE_ONCE(x,v) ((x)=(v))
#define dev_info(...) ((void)0)
#define dev_warn(...) ((void)0)
#define dev_err(...) ((void)0)
static void mutex_lock(int *m) {assert(m==&dsp.lock && !locked);locked=true;}
static void mutex_unlock(int *m) {assert(m==&dsp.lock && locked);locked=false;}
static void disable_irq(int irq)
{assert(locked && irq==42 && dsp.sleep_prepared && dsp.sleep_draining && !disables);disables++;}
static void flush_work(int *w)
{assert(locked && w==&dsp.power_work && disables && dsp.sleep_irq_disabled);flushes++;}
static int admit(struct n1x_sroot_client *c)
{assert(c==(void *)&dsp && locked && !dsp.shutdown_attempted && !disables);admissions++;return admit_error;}
static int mtk_pwrap_dev_shutdown(void *p,uint32_t *completed)
{assert(p==&dsp && locked && disables && flushes && !dsp.primary_owner);
 assert(completed==&dsp.shutdown_completed && !dsp.shutdown_power_off && !releases && !retires && !frees);
 powers++;if(!power_error)*completed=3;return power_error;}
static int mt8901_afe_sram_release_stopped(struct mt8901_afe_sram_buffer *b)
{assert(locked && dsp.shutdown_power_off && !dsp.boot_ready && powers>=1 && !frees);
 assert((b==&ring || b==&messages) && dsp.shutdown_provider_retired);release_attempts++;
 if(release_error_at==(int)release_attempts)return -EIO;releases++;return 0;}
static int retire(struct n1x_sroot_client *c)
{assert(locked && c==(void *)&dsp && dsp.shutdown_power_off && powers>=1);
 assert(dsp.primary_sram && dsp.processing_messages && !releases && !frees);
 retires++;return retire_error;}
static int quiesced(struct n1x_sroot_client *c)
{assert(c==(void *)&dsp && locked && dsp.shutdown_power_off);return 0;}
static const struct n1x_sroot_client_shutdown_ops ops={.admit=admit,.quiesced=quiesced,.retire=retire};
static void dma_free_coherent(struct device *d,size_t bytes,void *cpu,uint64_t dma)
{assert(locked && d==&device && bytes==target.dram_bytes+PAGE_SIZE && cpu==&dsp && dma==0xe0000000);
 assert(dsp.shutdown_power_off && releases==2 && retires && !retire_error && !frees);frees++;}
static void pm_runtime_dont_use_autosuspend(struct device *d)
{assert(locked && d==&device && frees && !pm_stages);pm_stages++;}
static void pm_runtime_disable(struct device *d)
{assert(locked && d==&device && pm_stages++==1);}
static void pm_runtime_put_noidle(struct device *d)
{assert(locked && d==&device && pm_stages++==2);pm_puts++;}
static int pm_runtime_set_suspended(struct device *d)
{assert(locked && d==&device && pm_stages++==3);return status_error;}
static void module_put(void *module)
{assert(module==THIS_MODULE && !locked && dsp.shutdown_done && !dsp.published && modules==1);modules--;}
static void *get_symbol(const char *name)
{
 if(!strcmp(name,"mtk_pwrap_dev_shutdown")) {
  if(missing==1)return NULL;symbols++;return mtk_pwrap_dev_shutdown;
 }
 assert(!strcmp(name,"mt8901_afe_sram_release_stopped"));
 if(missing==2)return NULL;symbols++;return mt8901_afe_sram_release_stopped;
}
static void put_symbol(void) {assert(symbols);symbols--;}
#define symbol_get(name) ((typeof(&name))get_symbol(#name))
#define symbol_put(name) put_symbol()
''' + shutdown + r'''
static void fresh(void)
{
 assert(!locked && !symbols);
 dsp=(struct n1x_adsp){.dev=&device,.target=&target,.irq=42,.pwrap=&dsp,
  .dram=&dsp,.dma=0xe0000000,.mailbox=mailbox,.published=true,.boot_ready=true,
  .primary_sram=&ring,.processing_messages=&messages,.processing_area=&messages,
  .shutdown_ops=&ops,.sroot_client=(void *)&dsp,.loader={true,true}};
 disables=flushes=powers=releases=retires=frees=pm_puts=0;
 admissions=release_attempts=pm_stages=0;modules=1;
 missing=admit_error=power_error=release_error_at=retire_error=status_error=0;
}
int main(void)
{
 for(unsigned i=1;i<=2;i++) {
  fresh();missing=i;assert(n1x_adsp_shutdown(&dsp,true)==-EOPNOTSUPP);
  assert(!symbols && !admissions && !disables && !powers && !frees);
 }
 for(unsigned i=0;i<7;i++) {
  fresh();
  switch(i){case 0:dsp.published=false;break;case 1:dsp.shutdown_ops=NULL;break;
   case 2:dsp.loader.accepted=false;break;case 3:dsp.loader.staging_released=false;break;
   case 4:dsp.sleep_prepared=true;break;case 5:dsp.sleep_suspended=true;break;
   case 6:dsp.primary_owner=&dsp;break;}
  assert(n1x_adsp_shutdown(&dsp,true)==(i<4?-EOPNOTSUPP:-EBUSY));
  assert(!symbols && !admissions && !disables && !powers && !frees);
 }
 fresh();admit_error=-EBUSY;
 assert(n1x_adsp_shutdown(&dsp,true)==-EBUSY && admissions==1 && !dsp.shutdown_attempted && !disables);
 for(unsigned i=0;i<3;i++) {
  fresh();power_error=i==0?-EBUSY:i==1?-ETIMEDOUT:-ENOTRECOVERABLE;
  assert(n1x_adsp_shutdown(&dsp,true)<0 && dsp.shutdown_error && dsp.shutdown_attempted);
  if(i==0) {
   assert(n1x_adsp_shutdown(&dsp,true)==-EBUSY && powers==2 && disables==1 && !frees);
   power_error=0;assert(!n1x_adsp_shutdown(&dsp,true) && powers==3 && frees==1);
  } else {
   for(unsigned repeat=0;repeat<8;repeat++)assert(n1x_adsp_shutdown(&dsp,true)==dsp.shutdown_error);
   assert(!symbols && disables==1 && powers==1 && !releases && !retires && !frees && modules==1);
  }
 }
 fresh();assert(!n1x_adsp_shutdown(&dsp,false) && dsp.shutdown_power_off && !frees && !retires);
 assert(!n1x_adsp_shutdown(&dsp,false) && powers==1 && !frees);
 assert(!n1x_adsp_shutdown(&dsp,true) && powers==1 && frees==1);
 for(unsigned i=0;i<4;i++) {
  fresh();
  if(i<2)release_error_at=i+1;else if(i==2)retire_error=-ENOTRECOVERABLE;
  else status_error=-EBUSY;
  int result=n1x_adsp_shutdown(&dsp,true);
  if(i<3) {
   assert(result<0 && dsp.shutdown_power_off && !dsp.shutdown_done && !frees && modules==1);
   release_error_at=retire_error=0;assert(!n1x_adsp_shutdown(&dsp,true));
  } else assert(!result);
  assert(dsp.shutdown_done && !dsp.shutdown_error && !dsp.published && !dsp.boot_ready);
  assert(!dsp.dram && !dsp.dma && !dsp.primary_sram && !dsp.processing_messages);
  assert(!symbols && powers==1 && releases==2 && frees==1 && pm_puts==1 && !modules && pm_stages==4);
  assert(!n1x_adsp_shutdown(&dsp,true) && powers==1 && frees==1 && !modules);
 }
 puts("DSP shutdown: unsupported/busy gates, IRQ drain, power failures, partial cleanup without power replay, DMA/PM/module release: PASS");
}
'''
    with tempfile.TemporaryDirectory(prefix='n1x-dsp-shutdown-') as directory:
        directory = Path(directory)
        harness, binary = directory / 'test.c', directory / 'test'
        harness.write_text(code)
        subprocess.run(['cc', '-I' + str(HERE), '-std=gnu11', '-Wall', '-Wextra',
                        '-Werror', '-Wno-misleading-indentation',
                        '-fsanitize=address,undefined', str(harness), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
