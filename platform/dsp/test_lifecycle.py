#!/usr/bin/env python3
"""Exercise the DSP primary-task implementation with injected OS/firmware edges."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent


def main():
    source = (ROOT / 'n1x_adsp.c').read_text()
    constants = source[source.index('#define ADSP_RX_OFFSET '):
                       source.index('static bool enable_boot;')]
    state = source[source.index('struct n1x_adsp_target {'):
                   source.index('static int n1x_adsp_group_member(')]
    lifecycle = source[source.index('static int n1x_adsp_primary_control('):
                       source.index('EXPORT_SYMBOL_GPL(n1x_adsp_primary_close);')]
    code = r'''
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "n1x_adsp_client.h"
#include "n1x_sroot_client.h"
typedef uint64_t u64;typedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;typedef uint64_t dma_addr_t;
typedef int spinlock_t;typedef int atomic_t;
struct device_driver {int unused;};
struct device {struct device_driver *driver;void *data;};
struct platform_driver {struct device_driver driver;};
struct mutex {int unused;};struct completion {bool done;};struct work_struct {int unused;};
#define DECLARE_KFIFO(name,type,size) struct {type data[size];} name
#define __iomem
#define ERR_PTR(err) ((void *)(intptr_t)(err))
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define IS_ERR(p) ((uintptr_t)(p) >= (uintptr_t)-4095)
#define IS_ERR_OR_NULL(p) (!(p) || IS_ERR(p))
#define spin_lock_irqsave(lock,flags) ((void)(lock),(flags)=0)
#define spin_unlock_irqrestore(lock,flags) ((void)(lock),(void)(flags))
#define synchronize_irq(irq) ((void)(irq))
#define GFP_KERNEL 0
#define EXPORT_SYMBOL_GPL(name)
''' + constants + state + r'''
static struct platform_driver n1x_adsp_driver;
static struct device device;
static struct n1x_adsp dsp;
static pthread_mutex_t device_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t request_mutex=PTHREAD_MUTEX_INITIALIZER;
static _Thread_local unsigned device_locked,request_locked;
static unsigned calls,prepares,refs,allocations,fail_at,bad_at,bad_echo;
static int allocation_error,lock_error,prepare_error;
static void device_lock(struct device *dev)
{assert(dev==&device && !device_locked);assert(!pthread_mutex_lock(&device_mutex));device_locked=1;}
static void device_unlock(struct device *dev)
{assert(dev==&device && device_locked==1 && !request_locked);device_locked=0;
 assert(!pthread_mutex_unlock(&device_mutex));}
static void *dev_get_drvdata(struct device *dev)
{assert(dev==&device && device_locked==1);return dev->data;}
static void mutex_lock(struct mutex *lock)
{assert(lock==&dsp.lock && device_locked==1 && !request_locked);
 assert(!pthread_mutex_lock(&request_mutex));request_locked=1;}
static int mutex_lock_interruptible(struct mutex *lock)
{if(lock_error)return lock_error;mutex_lock(lock);return 0;}
static void mutex_unlock(struct mutex *lock)
{assert(lock==&dsp.lock && device_locked==1 && request_locked==1);
 request_locked=0;assert(!pthread_mutex_unlock(&request_mutex));}
static struct device *get_device(struct device *dev)
{assert(dev==&device && device_locked==1 && request_locked==1);refs++;return dev;}
static void put_device(struct device *dev)
{assert(dev==&device && !device_locked && !request_locked && refs);refs--;}
static void *kzalloc(size_t bytes,int flags)
{assert(bytes==sizeof(struct n1x_adsp_primary) && !flags && device_locked && request_locked);
 if(allocation_error)return NULL;void *p=calloc(1,bytes);assert(p);allocations++;return p;}
static unsigned link_deletes;
static void device_link_del(struct device_link *link) {assert(link==(void *)0x1234 && !device_locked && !request_locked);link_deletes++;}
static void kfree(void *p) {assert(p && allocations);allocations--;free(p);}
static int n1x_adsp_prepare_primary_locked(struct n1x_adsp *context)
{assert(context==&dsp && device_locked==1 && request_locked==1);prepares++;return prepare_error;}
static void n1x_adsp_ipc_fail(struct n1x_adsp *context,int error)
{assert(context==&dsp);context->ipc_poisoned=true;context->ipc_error=error;}
static int n1x_adsp_transfer_locked(struct n1x_adsp *context,
 const struct n1x_adsp_ipc_request *request,struct n1x_adsp_ipc_reply *reply)
{
 static const u16 expected[]={1,9,2};
 assert(context==&dsp && device_locked==1 && request_locked==1);
 assert(dsp.primary_task_active && request->command==expected[calls%3]);
 assert(request->channel==7 && request->ack_mode==1 && !request->token);
 assert(!request->data_mode && !request->parameter1 && !request->parameter2 && !request->payload);
 calls++;if(fail_at==calls)return -ETIMEDOUT;
 memset(reply,0,sizeof(*reply));reply->packet[18]=(bad_at==calls && bad_echo==1)?8:7;
 reply->packet[21]=2;n1x_adsp_ipc_put16(reply->packet+22,
 request->command+(bad_at==calls && bad_echo==2));return 0;
}
''' + r'''
static int n1x_adsp_primary_stop_locked(struct n1x_adsp *dsp)
{assert(!dsp->primary_start_attempted);return 0;}
static bool auto_boot;
static int n1x_adsp_boot(struct n1x_adsp *dsp,bool kernel_client) {(void)dsp;(void)kernel_client;assert(0);return -EIO;}
''' + lifecycle + r'''
static void reset(void)
{
 assert(!refs && !allocations && !device_locked && !request_locked);
 memset(&dsp,0,sizeof(dsp));dsp.target=&targets[2];
 device.driver=&n1x_adsp_driver.driver;device.data=&dsp;
 calls=prepares=fail_at=bad_at=bad_echo=0;
 allocation_error=lock_error=prepare_error=0;
}
static void released(void) {assert(!refs && !allocations && !device_locked && !request_locked);}
static void *open_thread(void *arg) {(void)arg;return n1x_adsp_primary_open(&device);}
int main(void)
{
 reset();struct n1x_adsp_primary *client=n1x_adsp_primary_open(&device);
 assert(!IS_ERR(client) && dsp.primary_owner==client && refs==1 && allocations==1 && calls==1);
 assert(PTR_ERR(n1x_adsp_primary_open(&device))==-EBUSY && calls==1 && prepares==1);
 client->card_link=(void *)0x1234;
 assert(!n1x_adsp_primary_close(client) && calls==3 && !dsp.primary_task_active && link_deletes==1);
 assert(!dsp.primary_owner && !dsp.primary_task_error);released();
 client=n1x_adsp_primary_open(&device);assert(!IS_ERR(client) && calls==4);
 assert(!n1x_adsp_primary_close(client) && calls==6);released();
 for(unsigned stage=1;stage<=3;stage++){
  reset();fail_at=stage;client=n1x_adsp_primary_open(&device);
  if(stage==1)assert(PTR_ERR(client)==-ETIMEDOUT);
  else {assert(!IS_ERR(client));assert(n1x_adsp_primary_close(client)==-ETIMEDOUT);}
  assert(calls==stage && dsp.primary_task_active && !dsp.primary_owner);
  assert(dsp.primary_task_error==-ETIMEDOUT);released();
  assert(PTR_ERR(n1x_adsp_primary_open(&device))==-ETIMEDOUT && calls==stage);released();
 }
 for(unsigned stage=1;stage<=3;stage++)for(unsigned echo=1;echo<=2;echo++){
  reset();bad_at=stage;bad_echo=echo;client=n1x_adsp_primary_open(&device);
  if(stage==1)assert(PTR_ERR(client)==-EPROTO);
  else {assert(!IS_ERR(client));assert(n1x_adsp_primary_close(client)==-EPROTO);}
  assert(calls==stage && dsp.primary_task_active && !dsp.primary_owner);
  assert(dsp.primary_task_error==-EPROTO && dsp.ipc_poisoned && dsp.ipc_error==-EPROTO);released();
  assert(PTR_ERR(n1x_adsp_primary_open(&device))==-EPROTO && calls==stage);released();
 }
 reset();prepare_error=-EHOSTDOWN;
 assert(PTR_ERR(n1x_adsp_primary_open(&device))==-EHOSTDOWN && !calls && prepares==1);
 assert(!dsp.primary_task_active && !dsp.primary_owner && !dsp.primary_task_error);released();
 reset();allocation_error=1;
 assert(PTR_ERR(n1x_adsp_primary_open(&device))==-ENOMEM && !calls && !prepares);released();
 reset();lock_error=-EINTR;
 assert(PTR_ERR(n1x_adsp_primary_open(&device))==-EINTR && !calls && !prepares);released();
 reset();device.driver=NULL;
 assert(PTR_ERR(n1x_adsp_primary_open(&device))==-ENODEV && !calls && !prepares);released();
 assert(PTR_ERR(n1x_adsp_primary_open(NULL))==-EINVAL);
 assert(n1x_adsp_primary_close(NULL)==-EINVAL);
 assert(n1x_adsp_primary_close(ERR_PTR(-ENOMEM))==-EINVAL);released();
 reset();pthread_t threads[8];unsigned winners=0;
 for(unsigned i=0;i<8;i++)assert(!pthread_create(&threads[i],NULL,open_thread,NULL));
 for(unsigned i=0;i<8;i++){
  void *result;assert(!pthread_join(threads[i],&result));
  if(IS_ERR(result))assert(PTR_ERR(result)==-EBUSY);
  else {winners++;client=result;}
 }
 assert(winners==1 && calls==1 && prepares==1 && refs==1 && allocations==1);
 assert(!n1x_adsp_primary_close(client) && calls==3);released();
 puts("DSP task lifecycle: exclusive ownership, reopen, all request/echo failures and eight concurrent opens: PASS");
}
'''
    with tempfile.TemporaryDirectory(prefix='p16-dsp-lifecycle-') as temporary:
        path, binary = Path(temporary) / 'test.c', Path(temporary) / 'test'
        path.write_text(code)
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        '-Wno-misleading-indentation', '-fsanitize=address,undefined',
                        '-pthread', '-g', '-I' + str(ROOT), str(path), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=20)


if __name__ == '__main__':
    main()
