#!/usr/bin/env python3
"""Exercise actual period delivery and listener teardown with an in-flight IRQ."""
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent


def main():
    source = (HERE / 'n1x_adsp.c').read_text()
    state = source[source.index('struct n1x_adsp_target {'):
                   source.index('static int n1x_adsp_group_member(')]
    receive = source[source.index('static void n1x_adsp_period_receive('):
                     source.index('static irqreturn_t n1x_adsp_irq(')]
    close = source[source.index('static void n1x_adsp_primary_period_disable('):
                   source.index('EXPORT_SYMBOL_GPL(n1x_adsp_primary_close);')]
    api = source[source.index('int n1x_adsp_primary_set_period('):
                 source.index('/* Bind PM ordering to the actual ALSA card,')]
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
typedef pthread_mutex_t spinlock_t;typedef int atomic_t;
#define __iomem
#define DECLARE_KFIFO(name,type,size) struct {type data[size];} name
#define IS_ERR(p) ((uintptr_t)(p)>=(uintptr_t)-4095)
#define IS_ERR_OR_NULL(p) (!(p)||IS_ERR(p))
#define ERR_PTR(e) ((void *)(intptr_t)(e))
#define EXPORT_SYMBOL_GPL(name)
#define ADSP_RX_BYTES 288
#define ADSP_PRIMARY_TASK 7
#define ADSP_PROCESSING_TASK 16
struct device_driver {int unused;};struct platform_driver {struct device_driver driver;};
struct device {struct device_driver *driver;void *data;};
struct mutex {pthread_mutex_t native;};struct completion {int unused;};struct work_struct {int unused;};
''' + state + r'''
static struct n1x_adsp dsp;
static struct n1x_adsp_primary *primary;
static struct device device;
static struct platform_driver n1x_adsp_driver;
static _Thread_local bool in_irq;
static pthread_mutex_t events=PTHREAD_MUTEX_INITIALIZER,device_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t condition=PTHREAD_COND_INITIALIZER;
static unsigned irq_active,device_puts,frees,commands;
static bool callback_entered,callback_release,sync_waiting;
static atomic_bool operation_done;
static u8 packet[288];
static int atomic_read(atomic_t *p) {return *p;}
static void spin_take(spinlock_t *lock) {assert(lock==&dsp.ipc_lock);assert(!pthread_mutex_lock(lock));}
static void spin_drop(spinlock_t *lock) {assert(lock==&dsp.ipc_lock);assert(!pthread_mutex_unlock(lock));}
#define spin_lock_irqsave(lock,flags) ((flags)=0,spin_take(lock))
#define spin_unlock_irqrestore(lock,flags) ((void)(flags),spin_drop(lock))
static void mutex_lock(struct mutex *lock) {assert(!in_irq);assert(!pthread_mutex_lock(&lock->native));}
static void mutex_unlock(struct mutex *lock) {assert(!pthread_mutex_unlock(&lock->native));}
static void synchronize_irq(int irq)
{
 assert(!in_irq && irq==123);assert(!pthread_mutex_lock(&events));
 sync_waiting=true;assert(!pthread_cond_broadcast(&condition));
 while(irq_active)assert(!pthread_cond_wait(&condition,&events));
 assert(!pthread_mutex_unlock(&events));
}
static void device_lock(struct device *dev)
{assert(!in_irq && dev==&device);assert(!pthread_mutex_lock(&device_mutex));}
static void device_unlock(struct device *dev)
{assert(dev==&device);assert(!pthread_mutex_unlock(&device_mutex));}
static void *dev_get_drvdata(struct device *dev) {assert(dev==&device);return &dsp;}
static void device_link_del(struct device_link *link) {assert(!link);}
static void put_device(struct device *dev) {assert(dev==&device);device_puts++;}
static void kfree(void *p) {assert(p==primary);free(p);frees++;}
static int n1x_adsp_primary_command(struct n1x_adsp *context,u8 task,u16 command,u32 parameter)
{assert(context==&dsp && task==7 && !parameter && command==(commands?2:9));commands++;return 0;}
''' + r'''
static int n1x_adsp_primary_stop_locked(struct n1x_adsp *context)
{assert(!context->primary_start_attempted);return 0;}
''' + receive + close + api + r'''
struct listener {atomic_uint calls;int error;struct n1x_adsp_pcm_position position;bool block;};
static void callback(void *data,const struct n1x_adsp_pcm_position *position,int error)
{
 struct listener *listener=data;assert(in_irq && listener);
 listener->position=*position;listener->error=error;atomic_fetch_add(&listener->calls,1);
 if(listener->block){
  assert(!pthread_mutex_lock(&events));callback_entered=true;assert(!pthread_cond_broadcast(&condition));
  while(!callback_release)assert(!pthread_cond_wait(&condition,&events));
  assert(!pthread_mutex_unlock(&events));
  /* Pointer reads must remain non-sleeping while detach/close holds dsp.lock. */
  struct n1x_adsp_pcm_position copy;int err=n1x_adsp_primary_position(primary,&copy);
  assert(!err || err==-ENODATA);
 }
}
static void make_packet(u64 address,u32 counter)
{
 memset(packet,0,sizeof(packet));packet[18]=7;packet[20]=1;packet[22]=0x1b;
 n1x_adsp_ipc_put32(packet+24,96);n1x_adsp_pcm_put64(packet+0x30,address);
 n1x_adsp_ipc_put32(packet+0x74,counter);
}
static void *interrupt(void *unused)
{
 (void)unused;assert(!pthread_mutex_lock(&events));irq_active++;
 assert(!pthread_mutex_unlock(&events));in_irq=true;n1x_adsp_period_receive(&dsp,packet);in_irq=false;
 assert(!pthread_mutex_lock(&events));assert(irq_active);irq_active--;
 assert(!pthread_cond_broadcast(&condition));assert(!pthread_mutex_unlock(&events));return NULL;
}
static void reset(void)
{
 memset(&dsp,0,sizeof(dsp));assert(!pthread_mutex_init(&dsp.ipc_lock,NULL));
 assert(!pthread_mutex_init(&dsp.lock.native,NULL));
 primary=calloc(1,sizeof(*primary));assert(primary);primary->dev=&device;primary->dsp=&dsp;
 device.driver=&n1x_adsp_driver.driver;dsp.primary_owner=primary;dsp.primary_task_active=true;dsp.irq=123;
 dsp.target=&targets[2];dsp.primary_period_enabled=true;
 dsp.primary_host_pcm=(struct n1x_adsp_pcm_config){.address=0xe0001000,.bytes=7680,.channels=2,.sample_bits=16};
 callback_entered=callback_release=sync_waiting=false;irq_active=device_puts=frees=commands=0;
 atomic_store(&operation_done,false);make_packet(0xe0001780,5);
}
static void cleanup(bool closed)
{
 if(!closed)free(primary);
 assert(!pthread_mutex_destroy(&dsp.ipc_lock));assert(!pthread_mutex_destroy(&dsp.lock.native));
}
static void *detach(void *close_handle)
{
 int err=close_handle?n1x_adsp_primary_close(primary):n1x_adsp_primary_set_period(primary,NULL,NULL);
 assert(!err);atomic_store(&operation_done,true);return NULL;
}
int main(void)
{
 reset();struct listener listener={0};struct n1x_adsp_pcm_position position;
 assert(!n1x_adsp_primary_position(primary,&position) && !position.valid && !position.byte_offset);
 assert(!n1x_adsp_primary_set_period(primary,callback,&listener));
 assert(n1x_adsp_primary_set_period(primary,callback,&listener)==-EBUSY);
 interrupt(NULL);assert(listener.calls==1 && !listener.error && listener.position.byte_offset==1920);
 assert(!n1x_adsp_primary_position(primary,&position) && position.counter==5 && position.notifications==1);
 make_packet(0xe0001f00,4);interrupt(NULL);assert(listener.calls==1 && dsp.primary_position.counter==5);
 make_packet(0xe0001000,0);interrupt(NULL);assert(listener.calls==2 && !listener.position.byte_offset);
 packet[21]=2;interrupt(NULL);assert(listener.calls==2 && !dsp.primary_period_error);
 packet[21]=0;packet[19]=0x20;interrupt(NULL);assert(listener.calls==2);
 packet[19]=0;packet[18]=16;interrupt(NULL);assert(listener.calls==2);
 make_packet(0xe0001001,0);interrupt(NULL);assert(listener.calls==3 && listener.error==-ERANGE);
 struct n1x_adsp_pcm_position before;memset(&before,0xa5,sizeof(before));position=before;
 assert(n1x_adsp_primary_position(primary,&position)==-ERANGE && !memcmp(&before,&position,sizeof(before)));
 assert(!dsp.ipc_poisoned);make_packet(0xe0001780,6);interrupt(NULL);assert(listener.calls==3);
 assert(n1x_adsp_primary_set_period(primary,callback,&listener)==-ERANGE);
 assert(!n1x_adsp_primary_set_period(primary,NULL,NULL));cleanup(false);
 for(unsigned power=0;power<2;power++){
  reset();memset(&listener,0,sizeof(listener));
  assert(!n1x_adsp_primary_set_period(primary,callback,&listener));
  if(power)dsp.power_error=-EIO;else {dsp.ipc_poisoned=true;dsp.ipc_error=-ETIMEDOUT;}
  interrupt(NULL);assert(listener.calls==1 && listener.error==(power?-EHOSTDOWN:-ETIMEDOUT));
  assert(!listener.position.valid && !listener.position.notifications);
  interrupt(NULL);assert(listener.calls==1);
  assert(!n1x_adsp_primary_set_period(primary,NULL,NULL));cleanup(false);
 }
 for(unsigned close_handle=0;close_handle<2;close_handle++){
  reset();struct listener *data=calloc(1,sizeof(*data));assert(data);data->block=true;
  assert(!n1x_adsp_primary_set_period(primary,callback,data));pthread_t irq_thread,detach_thread;
  assert(!pthread_create(&irq_thread,NULL,interrupt,NULL));
  assert(!pthread_mutex_lock(&events));
  while(!callback_entered)assert(!pthread_cond_wait(&condition,&events));
  assert(!pthread_mutex_unlock(&events));
  assert(!pthread_create(&detach_thread,NULL,detach,(void *)(uintptr_t)close_handle));
  assert(!pthread_mutex_lock(&events));
  while(!sync_waiting)assert(!pthread_cond_wait(&condition,&events));
  assert(!atomic_load(&operation_done) && data->calls==1);
  callback_release=true;assert(!pthread_cond_broadcast(&condition));assert(!pthread_mutex_unlock(&events));
  assert(!pthread_join(irq_thread,NULL));assert(!pthread_join(detach_thread,NULL));
  assert(atomic_load(&operation_done) && data->calls==1 && !dsp.primary_period && !dsp.primary_period_data);
  free(data);make_packet(0xe0001f00,6);interrupt(NULL);
  if(close_handle)assert(device_puts==1 && frees==1 && commands==2 && !dsp.primary_period_enabled);
  else assert(!device_puts && !frees && dsp.primary_position.notifications==2);
  cleanup(close_handle);
 }
 reset();dsp.primary_owner=NULL;assert(n1x_adsp_primary_set_period(primary,callback,NULL)==-EINVAL);
 assert(n1x_adsp_primary_set_period(NULL,NULL,NULL)==-EINVAL);
 assert(n1x_adsp_primary_set_period(ERR_PTR(-ENOMEM),NULL,NULL)==-EINVAL);
 assert(n1x_adsp_primary_position(NULL,&position)==-EINVAL);
 assert(n1x_adsp_primary_position(primary,NULL)==-EINVAL);
 dsp.ipc_poisoned=true;dsp.ipc_error=-ETIMEDOUT;
 assert(n1x_adsp_primary_position(primary,&position)==-ETIMEDOUT);
 dsp.ipc_poisoned=false;dsp.power_error=-EIO;
 assert(n1x_adsp_primary_position(primary,&position)==-EHOSTDOWN);
 dsp.power_error=0;dsp.primary_period_enabled=false;
 assert(n1x_adsp_primary_position(primary,&position)==-ENODATA);cleanup(false);
 puts("DSP periods: bounded delivery, stale/error handling, atomic pointer reads and in-flight detach/close: PASS");
 return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='dsp-period-') as directory:
        directory = Path(directory)
        path, binary = directory / 'period.c', directory / 'period'
        path.write_text(code)
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        '-Wno-misleading-indentation', '-fsanitize=address,undefined',
                        '-pthread', '-g', '-I', str(HERE), str(path), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=20)


if __name__ == '__main__':
    main()
