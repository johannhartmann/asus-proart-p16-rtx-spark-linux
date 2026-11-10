#!/usr/bin/env python3
"""Exercise actual DSP stream transitions, failure retention and close ordering."""
from pathlib import Path
import re
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent


def main():
    source = (HERE / 'n1x_adsp.c').read_text()
    constants = source[source.index('#define ADSP_RX_OFFSET '):source.index('static bool enable_boot;')]
    state = source[source.index('struct n1x_adsp_target {'):source.index('static int n1x_adsp_group_member(')]
    lifecycle = source[source.index('static int n1x_adsp_primary_control('):
                       source.index('EXPORT_SYMBOL_GPL(n1x_adsp_primary_close);')]
    trigger = source[source.index('/* Caller holds dsp->lock. Task STOP'):
                     source.index('int n1x_adsp_primary_commit(')]
    header = re.sub(r'^#include.*\n', '', (HERE / 'mt8901-afe-sram.h').read_text(), flags=re.M)
    code = r'''
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "n1x_adsp_client.h"
#include "n1x_sroot_client.h"
typedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;typedef uint64_t u64,dma_addr_t;
typedef int spinlock_t;typedef int atomic_t;
#define __iomem
#define ERR_PTR(e) ((void *)(intptr_t)(e))
#define PTR_ERR(p) ((long)(intptr_t)(p))
#define IS_ERR(p) ((uintptr_t)(p)>=(uintptr_t)-4095)
#define IS_ERR_OR_NULL(p) (!(p)||IS_ERR(p))
#define DECLARE_KFIFO(name,type,size) struct {type entries[size];} name
#define READ_ONCE(x) (x)
#define GFP_KERNEL 0
#define EXPORT_SYMBOL_GPL(name)
#define spin_lock_irqsave(lock,flags) ((void)(lock),(flags)=0)
#define spin_unlock_irqrestore(lock,flags) ((void)(lock),(void)(flags))
struct device_driver {int unused;};struct device {struct device_driver *driver;void *data;};
struct platform_driver {struct device_driver driver;};
struct mutex {int unused;};struct completion {int unused;};struct work_struct {int unused;};
''' + header + constants + state + r'''
struct mt8901_afe_sram_buffer {bool published;};
static struct mt8901_afe_sram_buffer sram;
static struct n1x_adsp dsp;static struct platform_driver n1x_adsp_driver;static struct device device;
static struct mt8901_afe_sram_endpoint endpoint_data;
static pthread_mutex_t device_mutex=PTHREAD_MUTEX_INITIALIZER,request_mutex=PTHREAD_MUTEX_INITIALIZER;
static _Thread_local unsigned dev_locked,request_locked;
static unsigned calls,refs,allocations,irq_stops,syncs,retirements;
static atomic_uint symbols;
static unsigned missing,fail_at,bad_at,bad_field,power_at,period_at;
static int lock_error,endpoint_error,irq_stop_error;
static bool power_in_irq_stop;
static u16 commands[32];static u8 tasks[32];
static int atomic_read(atomic_t *value) {return *value;}
static void device_lock(struct device *dev)
{assert(dev==&device && !dev_locked);assert(!pthread_mutex_lock(&device_mutex));dev_locked=1;}
static void device_unlock(struct device *dev)
{assert(dev==&device && dev_locked && !request_locked);dev_locked=0;assert(!pthread_mutex_unlock(&device_mutex));}
static void *dev_get_drvdata(struct device *dev) {assert(dev==&device && dev_locked);return dev->data;}
static void mutex_lock(struct mutex *lock)
{assert(lock==&dsp.lock && dev_locked && !request_locked);assert(!pthread_mutex_lock(&request_mutex));request_locked=1;}
static int mutex_lock_interruptible(struct mutex *lock)
{if(lock_error)return lock_error;mutex_lock(lock);return 0;}
static void mutex_unlock(struct mutex *lock)
{assert(lock==&dsp.lock && request_locked);request_locked=0;assert(!pthread_mutex_unlock(&request_mutex));}
static struct device *get_device(struct device *dev) {assert(dev==&device && request_locked);refs++;return dev;}
static void put_device(struct device *dev) {assert(dev==&device && !dev_locked && refs);refs--;}
static void *kzalloc(size_t bytes,int flags)
{assert(request_locked && bytes==sizeof(struct n1x_adsp_primary) && !flags);void *p=calloc(1,bytes);assert(p);allocations++;return p;}
static void device_link_del(struct device_link *link) {assert(!link);}
static void kfree(void *p) {assert(allocations);allocations--;free(p);}
static void synchronize_irq(int irq) {assert(irq==dsp.irq && request_locked);syncs++;}
static int n1x_adsp_prepare_primary_locked(struct n1x_adsp *context)
{assert(context==&dsp && request_locked);return 0;}
static void n1x_adsp_ipc_fail(struct n1x_adsp *context,int error)
{assert(context==&dsp);dsp.ipc_poisoned=true;dsp.ipc_error=error;}
static int n1x_adsp_transfer_locked(struct n1x_adsp *context,const struct n1x_adsp_ipc_request *request,
 struct n1x_adsp_ipc_reply *reply)
{
 assert(context==&dsp && dev_locked && request_locked && dsp.primary_task_active);
 if(dsp.power_error)return -EHOSTDOWN;if(dsp.ipc_poisoned)return -ENOTRECOVERABLE;
 assert(!request->token && request->ack_mode==1 && !request->data_mode && !request->payload);
 assert(request->channel==7 || request->channel==16);
 if(request->command==0x0f){
  assert(dsp.primary_start_attempted && !request->parameter1);
  assert(request->parameter2==(request->channel==7?16:0));
 }else{
  assert(request->command==1 || request->command==2 || request->command==9 || request->command==0x202 || request->command==0x10);
  assert(!request->parameter2 && request->parameter1==(request->command==0x202?1:0));
 }
 assert(calls<32);tasks[calls]=request->channel;commands[calls++]=request->command;
 if(fail_at==calls)return -ETIMEDOUT;
 memset(reply,0,sizeof(*reply));reply->packet[18]=request->channel+(bad_at==calls && bad_field==1);
 reply->packet[21]=2;n1x_adsp_ipc_put16(reply->packet+22,request->command+(bad_at==calls && bad_field==2));
 if(power_at==calls)dsp.power_error=-EIO;if(period_at==calls)dsp.primary_period_error=-ERANGE;
 return 0;
}
int mt8901_afe_sram_endpoint(struct mt8901_afe_sram_buffer *buffer,struct mt8901_afe_sram_endpoint *value,size_t bytes)
{assert(buffer==&sram && bytes==sizeof(*value) && dev_locked && request_locked);
 if(endpoint_error)return endpoint_error;*value=endpoint_data;return 0;}
int mt8901_afe_sram_stop_irq(struct mt8901_afe_sram_buffer *buffer,unsigned core)
{assert(buffer==&sram && core==3 && dev_locked && request_locked && calls==5);
 assert(tasks[3]==7 && commands[3]==0x10 && tasks[4]==16 && commands[4]==0x10);irq_stops++;
 if(power_in_irq_stop)dsp.power_error=-EIO;if(irq_stop_error)return irq_stop_error;
 endpoint_data.irq_prepared=false;return 0;}
static void *get_symbol(const char *name)
{unsigned n=!strcmp(name,"mt8901_afe_sram_endpoint")?1:!strcmp(name,"mt8901_afe_sram_stop_irq")?2:0;
 assert(n);if(missing==n)return NULL;atomic_fetch_add(&symbols,1);
 return n==1?(void *)mt8901_afe_sram_endpoint:(void *)mt8901_afe_sram_stop_irq;}
static void put_symbol(const char *name) {(void)name;assert(atomic_fetch_sub(&symbols,1));}
#define symbol_get(name) ((typeof(&name))get_symbol(#name))
#define symbol_put(name) put_symbol(#name)
static bool auto_boot;
static int n1x_adsp_boot(struct n1x_adsp *dsp,bool kernel_client) {(void)dsp;(void)kernel_client;assert(0);return -EIO;}
''' + lifecycle + trigger + r'''
static void notice(void *data,const struct n1x_adsp_pcm_position *position,int error)
{(void)data;(void)position;(void)error;assert(0);}
static void retire(struct mt8901_afe_sram_buffer *buffer)
{assert(buffer==&sram && dsp.primary_owner && request_locked && !dsp.primary_period && !dsp.primary_period_data);retirements++;}
static struct n1x_adsp_primary *setup(void)
{
 assert(!refs && !allocations && !atomic_load(&symbols) && !dev_locked && !request_locked);
 memset(&dsp,0,sizeof(dsp));dsp.target=&targets[2];device.driver=&n1x_adsp_driver.driver;device.data=&dsp;
 calls=irq_stops=syncs=retirements=missing=fail_at=bad_at=bad_field=power_at=period_at=0;
 lock_error=endpoint_error=irq_stop_error=0;power_in_irq_stop=false;
 memset(commands,0,sizeof(commands));memset(tasks,0,sizeof(tasks));sram.published=true;
 struct n1x_adsp_primary *p=n1x_adsp_primary_open(&device);assert(!IS_ERR(p) && calls==1);
 dsp.primary_pcm_configured=dsp.primary_pcm_prepared=dsp.processing_active=dsp.primary_period_enabled=true;
 dsp.primary_pcm_attempted=true;dsp.primary_sram=&sram;dsp.primary_retire=retire;dsp.primary_write_publications=1;
 dsp.primary_afe_pcm=(struct n1x_adsp_pcm_config){.address=0x1a6c0000,.bytes=3840,.rate=48000,.channels=2,.sample_bits=16,.hardware=1,.period_frames=480,.periods=2};
 endpoint_data=(struct mt8901_afe_sram_endpoint){.abi_version=2,.published=true,.irq_prepared=true,
 .memory={.afe_address=0x1a6c0000,.bytes=3840},.rate=48000,.channels=2,.sample_bits=16,.period_frames=480,.periods=2};
 dsp.primary_period=notice;dsp.primary_period_data=(void *)0x1234;return p;
}
static void closed(void) {assert(retirements==1 && !dsp.primary_retire);assert(!refs && !allocations && !atomic_load(&symbols) && !dev_locked && !request_locked);}
static void *start_thread(void *p) {return (void *)(intptr_t)n1x_adsp_primary_start(p);}
static void *stop_thread(void *p) {return (void *)(intptr_t)n1x_adsp_primary_stop(p);}
int main(void)
{
 struct n1x_adsp_primary *p=setup();
 assert(n1x_adsp_primary_stop(p)==-EINVAL && calls==1 && !irq_stops);
 pthread_t threads[8];void *result;
 for(unsigned i=0;i<8;i++)assert(!pthread_create(&threads[i],NULL,start_thread,p));
 for(unsigned i=0;i<8;i++){assert(!pthread_join(threads[i],&result));assert(!result);}
 assert(calls==3 && dsp.primary_running && dsp.primary_start_attempted && !atomic_load(&symbols));
 for(unsigned i=0;i<8;i++)assert(!pthread_create(&threads[i],NULL,stop_thread,p));
 for(unsigned i=0;i<8;i++){assert(!pthread_join(threads[i],&result));assert(!result);}
 assert(calls==5 && irq_stops==1 && dsp.primary_stopped && !dsp.primary_running && syncs);
 assert(!dsp.primary_period_enabled && !dsp.primary_period && !dsp.primary_period_data);
 assert(n1x_adsp_primary_start(p)==-EINVAL && calls==5);
 assert(!n1x_adsp_primary_close(p) && calls==10);closed();
 const u16 expected[]={1,0x0f,0x0f,0x10,0x10,9,2,9,0x202,2};
 const u8 expected_tasks[]={7,16,7,7,16,7,7,16,16,16};
 assert(!memcmp(commands,expected,sizeof(expected)) && !memcmp(tasks,expected_tasks,sizeof(expected_tasks)));
 p=setup();assert(!n1x_adsp_primary_start(p));
 assert(!n1x_adsp_primary_close(p) && calls==10 && irq_stops==1 && !dsp.primary_stopped);closed();
 for(unsigned fault=0;fault<26;fault++){
  p=setup();
  switch(fault){
  case 0:missing=1;break;case 1:device.driver=NULL;break;case 2:lock_error=-EINTR;break;
  case 3:dsp.primary_owner=NULL;break;case 4:dsp.primary_task_active=false;break;
  case 5:dsp.primary_pcm_prepared=false;break;case 6:dsp.processing_active=false;break;
  case 7:dsp.primary_sram=NULL;break;case 8:dsp.ipc_poisoned=true;break;case 9:dsp.power_error=-EIO;break;
  case 10:dsp.primary_period_error=-ERANGE;break;case 11:dsp.primary_write_publications=0;break;
  case 12:dsp.primary_period_enabled=false;break;case 13:endpoint_error=-EBUSY;break;
  case 14:endpoint_data.abi_version=1;break;case 15:endpoint_data.published=false;break;
  case 16:endpoint_data.irq_prepared=false;break;case 17:endpoint_data.memory.afe_address++;break;
  case 18:endpoint_data.memory.bytes++;break;case 19:endpoint_data.memif=1;break;
  case 20:endpoint_data.irq=1;break;case 21:endpoint_data.rate=44100;break;case 22:endpoint_data.sample_bits=32;break;case 23:endpoint_data.channels=1;break;
  case 24:endpoint_data.period_frames=481;break;case 25:endpoint_data.periods=3;break;
  }
  assert(n1x_adsp_primary_start(p)<0 && calls==1 && !dsp.primary_start_attempted && !atomic_load(&symbols));
  missing=0;device.driver=&n1x_adsp_driver.driver;lock_error=0;dsp.primary_owner=p;dsp.primary_task_active=true;
  dsp.ipc_poisoned=false;dsp.power_error=0;dsp.primary_period_error=0;
  dsp.processing_active=true;dsp.primary_sram=&sram;
  assert(!n1x_adsp_primary_close(p) && calls==6 && !irq_stops);closed();
 }
 for(unsigned stage=2;stage<=5;stage++)for(unsigned kind=0;kind<5;kind++){
  p=setup();if(stage>=4)assert(!n1x_adsp_primary_start(p));
  int error=kind==0?-ETIMEDOUT:kind<3?-EPROTO:kind==3?-EIO:-ERANGE;
  if(kind==0)fail_at=stage;else if(kind<3){bad_at=stage;bad_field=kind;}
  else if(kind==3)power_at=stage;else period_at=stage;
  int ret=stage<4?n1x_adsp_primary_start(p):n1x_adsp_primary_stop(p);
  if(kind==4 && stage>=4){
   assert(!ret && calls==5 && irq_stops==1 && dsp.primary_stopped);
   assert(!n1x_adsp_primary_close(p) && calls==10);closed();continue;
  }
  assert(ret==error && calls==stage && dsp.primary_task_error==error && !irq_stops && !atomic_load(&symbols));
  assert(n1x_adsp_primary_start(p)==error && n1x_adsp_primary_stop(p)==error && calls==stage);
  assert(n1x_adsp_primary_close(p)==error && calls==stage);closed();
 }
 for(unsigned kind=0;kind<2;kind++){
  p=setup();assert(!n1x_adsp_primary_start(p));irq_stop_error=kind?0:-EIO;power_in_irq_stop=kind;
  assert(n1x_adsp_primary_stop(p)==-EIO && calls==5 && irq_stops==1 && dsp.primary_task_error==-EIO);
  assert(!dsp.primary_stopped && dsp.primary_running);
  assert(n1x_adsp_primary_close(p)==-EIO && calls==5 && irq_stops==1);closed();
 }
 p=setup();assert(!n1x_adsp_primary_start(p));missing=2;
 assert(n1x_adsp_primary_stop(p)==-EOPNOTSUPP && calls==3 && !dsp.primary_task_error);
 missing=0;assert(!n1x_adsp_primary_close(p) && calls==10);closed();
 assert(n1x_adsp_primary_start(NULL)==-EINVAL && n1x_adsp_primary_stop(ERR_PTR(-ENOMEM))==-EINVAL);
 puts("DSP triggers: native task order, ABI/readiness guards, all ACK/IRQ failures, close cleanup and eight concurrent start/stop callers: PASS");
 return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='dsp-trigger-') as directory:
        directory = Path(directory)
        source, binary = directory / 'trigger.c', directory / 'trigger'
        source.write_text(code)
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        '-Wno-misleading-indentation', '-fsanitize=address,undefined',
                        '-pthread', '-g', '-I', str(HERE), str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
