#!/usr/bin/env python3
"""Compile the actual DSP boot/IRQ handlers against fault-injected OS edges."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent


def test_remove(source):
    remove = source[source.index('static void n1x_adsp_remove('):
                    source.index('static int n1x_adsp_runtime_suspend(')]
    harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <errno.h>
struct device {int unused;};
struct work_struct {bool pending;};
struct n1x_adsp {int irq;struct work_struct power_work;void *pwrap;};
struct platform_device {struct device dev;};
static struct platform_device pdev;
static struct n1x_adsp dsp;
static int step,resume_result;
static struct n1x_adsp *platform_get_drvdata(struct platform_device *p)
{assert(p==&pdev);return &dsp;}
static void devm_free_irq(struct device *dev,int irq,void *data)
{assert(dev==&pdev.dev && irq==234 && data==&dsp && step++==0);}
static void cancel_work_sync(struct work_struct *work)
{assert(work==&dsp.power_work && step++==1);work->pending=false;}
static int pm_runtime_resume_and_get(struct device *dev)
{assert(dev==&pdev.dev && !dsp.power_work.pending && step++==2);return resume_result;}
static void pm_runtime_dont_use_autosuspend(struct device *dev)
{assert(dev==&pdev.dev && step++==3);}
static void pm_runtime_disable(struct device *dev)
{assert(dev==&pdev.dev && step++==4);}
static void mtk_pwrap_dev_remove(void *p)
{assert(p==&dsp && step++==5);}
static void pm_runtime_put_noidle(struct device *dev)
{assert(dev==&pdev.dev && step++==6 && resume_result>=0);}
''' + remove + r'''
int main(void)
{
 for(unsigned fail=0;fail<2;fail++) {
  step=0;resume_result=fail?-EIO:0;dsp.irq=234;dsp.pwrap=&dsp;dsp.power_work.pending=true;
  n1x_adsp_remove(&pdev);assert(step==(fail?6:7));
 }
}
'''
    with tempfile.TemporaryDirectory() as temporary:
        code, binary = Path(temporary) / 'remove.c', Path(temporary) / 'remove'
        code.write_text(harness)
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', '-g', str(code), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


def main():
    source = (ROOT / 'n1x_adsp.c').read_text()
    state = source[source.index('struct n1x_adsp_target {'):source.index('static int n1x_adsp_group_member(')]
    handlers = source[source.index('static void n1x_adsp_power_work('):source.index('static ssize_t boot_store(')]
    harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include "n1x_adsp_client.h"
#include "n1x_sroot_client.h"
#include "n1x_sroot_firmware.h"
typedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;typedef uint64_t u64,dma_addr_t;
typedef int irqreturn_t;
#define __iomem
#define SHA256_DIGEST_SIZE 32
#define ADSP_RX_OFFSET 0x20
#define ADSP_CONFIG_OFFSET 0x3a0
#define ADSP_RX_BYTES 0x120
#define ADSP_OUT_STATUS 0x104
#define ADSP_OUT_CLEAR 0x10c
#define CAP_SYS_RAWIO 17
#define THIS_MODULE ((void *)1)
#define DMA_BIT_MASK(n) ((1ULL<<(n))-1)
#define GFP_KERNEL 0
#define IRQ_NONE 0
#define IRQ_HANDLED 1
#define BIT(n) (1U<<(n))
#define __ffs(n) __builtin_ctz(n)
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define spin_lock_irqsave(lock,flags) ((void)(lock),(flags)=0)
#define spin_unlock_irqrestore(lock,flags) ((void)(lock),(void)(flags))
#define lower_32_bits(n) ((u32)(n))
#define msecs_to_jiffies(n) (n)
#define dev_info(...) ((void)0)
#define dev_err(...) ((void)0)
#define dev_err_ratelimited(...) ((void)0)
typedef int atomic_t;
typedef int spinlock_t;
struct work_struct {bool pending;};
struct mock_fifo {u32 data[16];unsigned head,tail,count;};
#define DECLARE_KFIFO(name,type,size) struct mock_fifo name
#define container_of(ptr,type,member) ((type *)((char *)(ptr)-offsetof(type,member)))
static int atomic_read(atomic_t *p) {return *p;}
static void atomic_inc(atomic_t *p) {++*p;}
static int atomic_cmpxchg(atomic_t *p,int old,int value) {int before=*p;if(before==old)*p=value;return before;}
static int schedule_work(struct work_struct *work) {work->pending=true;return 1;}
static unsigned kfifo_in_spinlocked(struct mock_fifo *fifo,const u32 *value,unsigned count,spinlock_t *lock)
{(void)lock;assert(count==1);if(fifo->count==16)return 0;fifo->data[fifo->head++%16]=*value;fifo->count++;return 1;}
static unsigned kfifo_out_spinlocked(struct mock_fifo *fifo,u32 *value,unsigned count,spinlock_t *lock)
{(void)lock;assert(count==1);if(!fifo->count)return 0;*value=fifo->data[fifo->tail++%16];fifo->count--;return 1;}
struct power_cntl_scmi_data {u8 requestId;u32 customdata[3];};
struct _power_cntrl_request {struct device *dev;void *InBuffer;size_t InBufferSize;
 void *OutBuffer;size_t OutBufferSize,BytesReturned;};
struct device_driver { const char *name; };
struct device { struct device_driver *driver; } device;
struct completion { bool done; };
struct mutex { int unused; };
struct firmware { const u8 *data;size_t size; };
static bool enable_boot=true,privileged=true,provider=true;
static int fault,reads,writes,pm_refs,module_refs,provider_leases,uploads,frees,waits;

static u8 firmware_bytes[631436];
static struct firmware firmware={firmware_bytes,sizeof(firmware_bytes)};
static void *allocation;
static u32 shared_memory[256],mailbox_memory[1024];
static int n1x_adsp_dma_gate(struct device *d) {assert(d==&device);return fault==2?-EOPNOTSUPP:0;}
static bool capable(int cap) {assert(cap==CAP_SYS_RAWIO);return privileged;}
static struct device *n1x_adsp_find_device(struct device *consumer,const char *name) {
 assert(consumer==&device && !strcmp(name,"NVDA8301"));return NULL;
}
static void device_lock(struct device *d) {(void)d;assert(0);}
static void device_unlock(struct device *d) {(void)d;assert(0);}
static void *dev_get_drvdata(struct device *d) {(void)d;assert(0);return NULL;}
static void put_device(struct device *d) {assert(!d);}
static int request_firmware_direct(const struct firmware **fw,const char *name,struct device *d) {
 assert(d==&device && !strcmp(name,"nvidia/n1x/hifi5-0-mt8901-signed.bin"));
 assert(provider_leases==1 && !reads && !writes);if(fault==1)return -ENOENT;*fw=&firmware;return 0;
}
static void release_firmware(const struct firmware *fw) {assert(fw==&firmware);}
static int dma_set_mask_and_coherent(struct device *d,u64 mask) {
 assert(d==&device && mask==0xffffffff);return fault==3?-EIO:0;
}
static int pm_runtime_resume_and_get(struct device *d) {
 assert(d==&device);if(fault==4)return -EIO;pm_refs++;return 0;
}
static void pm_runtime_put(struct device *d) {assert(d==&device && pm_refs==1);pm_refs--;}
static void *dma_alloc_coherent(struct device *d,size_t bytes,dma_addr_t *dma,int flag) {
 assert(d==&device && bytes==24U<<20 && flag==GFP_KERNEL && pm_refs==1 && !module_refs);
 if(fault==5)return NULL;allocation=malloc(bytes);assert(allocation);*dma=fault==6?0xd0000000:0xe0000000;
 return allocation;
}
static void dma_free_coherent(struct device *d,size_t bytes,void *cpu,dma_addr_t dma) {
 assert(d==&device && bytes==24U<<20 && cpu==allocation && dma && !writes && !module_refs);
 free(cpu);allocation=NULL;frees++;
}
static bool try_module_get(void *m) {assert(m==THIS_MODULE && pm_refs==1);if(fault==9)return false;module_refs++;return true;}
static void module_put(void *m) {assert(m==THIS_MODULE && module_refs==1 && !writes);module_refs--;}
static void dma_wmb(void) {assert(pm_refs==1 && module_refs==1 && !writes);}
static u32 readl(const void *address) {assert(pm_refs==1);reads++;return *(const u32 *)address;}
static void writel(u32 value,void *address) {assert(pm_refs==1 && module_refs==1);writes++;*(u32 *)address=value;}
static void memcpy_fromio(void *dest,const void *src,size_t count) {assert(pm_refs==1 && count==ADSP_RX_BYTES);memcpy(dest,src,count);}
static u16 get_unaligned_le16(const u8 *p) {return p[0]|(u16)p[1]<<8;}
static void complete(struct completion *c) {c->done=true;}
static void reinit_completion(struct completion *c) {assert(!c->done);c->done=false;}
static unsigned long wait_for_completion_timeout(struct completion *c,unsigned long ticks) {
 assert(ticks==30000);waits++;return c->done?1:0;
}
static int upload_stub(struct n1x_sroot_client *client,u32 id,const u8 *image,size_t bytes,struct n1x_sroot_client_result_v2 *result);
static int power_calls,power_reply,in_irq;
static u32 power_value,power_values[16];
static int mtk_send_power_control_req(struct _power_cntrl_request *request)
{
 struct power_cntl_scmi_data *data=request->InBuffer;
 assert(!in_irq && request->dev==&device && request->InBufferSize==16);
 assert(!request->OutBuffer && !request->OutBufferSize && !request->BytesReturned);
 assert(data->requestId==0 && data->customdata[0]==1 && data->customdata[2]==0);
 assert(power_calls<16);power_values[power_calls++]=data->customdata[1];
 power_value=data->customdata[1];return power_reply;
}
static u32 get_unaligned_le32(const u8 *p) {return (u32)p[0]|(u32)p[1]<<8|(u32)p[2]<<16|(u32)p[3]<<24;}
static int prepare_stub(struct n1x_sroot_client *client);
static int publish_stub(struct n1x_sroot_client *client);
static int cancel_stub(struct n1x_sroot_client *client);
static const struct n1x_sroot_client_ops test_sroot_ops={
 .prepare=prepare_stub,.publish=publish_stub,.cancel=cancel_stub,.upload=upload_stub};
''' + state + r'''
static struct n1x_adsp dsp;
''' + source[source.index('static void n1x_adsp_ipc_fail('):
             source.index('static bool n1x_adsp_tx_idle(')] + handlers + r'''
static bool provider_published;
static int prepare_stub(struct n1x_sroot_client *client)
{assert(client==(void *)&dsp && !provider_leases && !writes && !pm_refs);
 if(!provider)return -EHOSTDOWN;provider_leases++;return 0;}
static int publish_stub(struct n1x_sroot_client *client)
{assert(client==(void *)&dsp && provider_leases==1 && module_refs==1 && !writes && !provider_published);
 if(fault==18)return -EIO;provider_published=true;return 0;}
static int cancel_stub(struct n1x_sroot_client *client)
{assert(client==(void *)&dsp && provider_leases==1 && !provider_published);provider_leases--;return 0;}
static int upload_stub(struct n1x_sroot_client *client,u32 id,const u8 *image,size_t bytes,struct n1x_sroot_client_result_v2 *result) {
 assert(client==(void *)&dsp && provider_published);
 assert(id==0xc0304 && image==firmware.data && bytes==firmware.size);
 assert(module_refs==1 && pm_refs==1 && provider_leases==1 && dsp.published && dsp.attempted && writes==2);
 assert(shared_memory[ADSP_CONFIG_OFFSET/4]==0xe0000000 && shared_memory[ADSP_CONFIG_OFFSET/4+2]==24U<<20);
 uploads++;result->published=1;if(fault==10)return -ETIMEDOUT;result->accepted=1;result->reply_valid=1;result->reply_header=0x18;result->staging_released=1;
 if(fault==13)result->published=0;if(fault==14)result->reply_valid=0;if(fault==15)result->accepted=0;
 if(fault==16)result->staging_released=0;if(fault==17)result->reply_header=0x118;
 if(fault!=11) {
  u8 *packet=(u8 *)shared_memory+ADSP_RX_OFFSET;
  packet[19]=fault==12?0:0x20;packet[22]=2;packet[23]=0xf0;
  mailbox_memory[ADSP_OUT_STATUS/4]=8;
  assert(n1x_adsp_irq(0,&dsp)==IRQ_HANDLED);
  assert(mailbox_memory[ADSP_OUT_CLEAR/4]==8 && shared_memory[4]==0);
 }
 return 0;
}
static void image_put32(u8 *p,u32 value) {for(unsigned i=0;i<4;i++)p[i]=value>>(8*i);}
static void make_image(u8 *p,size_t bytes,u32 id)
{
 assert(bytes>=83);memset(p,0,bytes);p[0]=0x59;
 u8 *n=p+3;image_put32(n,1);image_put32(n+4,2);image_put32(n+8,0xefbeadde);
 image_put32(n+12,0xefbeadde);image_put32(n+16,id);image_put32(n+32,80);
 image_put32(n+44,0xefbeadde);image_put32(n+48,id);image_put32(n+56,80);
 image_put32(n+64,bytes-83);image_put32(n+76,0xefbeadde);
}
static void reset(void) {
 free(allocation);allocation=NULL;memset(&dsp,0,sizeof(dsp));
 memset(shared_memory,0,sizeof(shared_memory));memset(mailbox_memory,0,sizeof(mailbox_memory));
 enable_boot=privileged=provider=true;fault=reads=writes=pm_refs=module_refs=provider_leases=uploads=frees=waits=0;
 power_calls=power_reply=in_irq=0;power_value=0;
 provider_published=false;dsp.sroot_ops=&test_sroot_ops;dsp.sroot_client=(void *)&dsp;
 dsp.dev=&device;dsp.target=&targets[0];dsp.firmware=dsp.target->firmware;dsp.shared=shared_memory;dsp.mailbox=mailbox_memory;
 firmware.size=sizeof(firmware_bytes);make_image(firmware_bytes,firmware.size,0xc0304);
}
static void power_notification(unsigned type,u32 value)
{
 u8 *packet=(u8 *)shared_memory+ADSP_RX_OFFSET;
 packet[19]=type<<4;packet[22]=5;packet[23]=0xf0;
 for(unsigned i=0;i<4;i++)packet[24+i]=value>>(8*i);
 mailbox_memory[ADSP_OUT_STATUS/4]=8;
 in_irq=1;assert(n1x_adsp_irq(0,&dsp)==IRQ_HANDLED);in_irq=0;
}
static unsigned period_calls;
static int period_error;
static void period_callback(void *data,const struct n1x_adsp_pcm_position *position,int error)
{
 assert(in_irq && data==&dsp && shared_memory[4]==0);
 assert(position->byte_offset==1920 && position->counter==5 && position->notifications==1);
 period_calls++;period_error=error;
}
int main(void) {
 reset();dsp.sleep_prepared=true;
 assert(n1x_adsp_boot(&dsp, false)==-EBUSY);
 assert(!reads && !writes && !pm_refs && !module_refs && !provider_leases && !dsp.attempted);
 for(int f=1;f<=18;f++) {
  reset();fault=f;
  if(f==7)mailbox_memory[ADSP_OUT_STATUS/4]=1;
  if(f==8){shared_memory[ADSP_CONFIG_OFFSET/4]=0xe0000000;shared_memory[ADSP_CONFIG_OFFSET/4+2]=24U<<20;}
  assert(n1x_adsp_boot(&dsp, false)<0);assert(provider_leases==(f>=10 && f<=17));
  if(f<10 || f==18)assert(!writes && !pm_refs && !module_refs && !dsp.published && !allocation && !uploads);
  else {
   assert(dsp.published && dsp.attempted && pm_refs==1 && module_refs==1 && allocation && !frees && uploads==1);
   if(f<=12)assert(!dsp.boot_ready);else assert(dsp.boot_ready && dsp.error==-EPROTO && !waits);
   assert(n1x_adsp_boot(&dsp, false)==-EALREADY);
  }
 }
 reset();assert(!n1x_adsp_boot(&dsp, false));assert(dsp.boot_ready && dsp.loader.accepted && dsp.notifications==1);
 assert(module_refs==1 && pm_refs==1 && provider_leases==1 && !frees && waits==1);
 reset();shared_memory[ADSP_CONFIG_OFFSET/4]=0xbf0676f6;shared_memory[ADSP_CONFIG_OFFSET/4+2]=0xb6dd3e39;
 assert(!n1x_adsp_boot(&dsp, false) && dsp.boot_ready); /* Observed uninitialized SRAM is not a DMA window. */
 reset();privileged=false;assert(!n1x_adsp_boot(&dsp, true) && dsp.boot_ready);
 reset();enable_boot=false;assert(n1x_adsp_boot(&dsp, true)==-EPERM && !writes && !dsp.published);
 for(int guard=0;guard<6;guard++) {
  reset();if(guard==0)enable_boot=false;if(guard==1)privileged=false;if(guard==2)provider=false;
  if(guard==3)firmware_bytes[0]=0;if(guard==4)firmware.size--;if(guard==5)dsp.target=&targets[1];
  assert(n1x_adsp_boot(&dsp, false)<0);assert(!reads && !writes && !pm_refs && !module_refs && !provider_leases);
 }
 reset();assert(n1x_adsp_irq(0,&dsp)==IRQ_NONE && !reads && !writes);
 reset();assert(!n1x_adsp_boot(&dsp, false));power_notification(2,0x78563412);
 assert(dsp.power_work.pending && dsp.power_queued==1 && !dsp.power_completed && !power_calls);
 dsp.power_work.pending=false;n1x_adsp_power_work(&dsp.power_work);
 assert(power_calls==1 && power_value==0x78563412 && dsp.power_completed==1 && !dsp.power_error);
 /* Wrong notification class must never submit an SSPM request. */
 reset();assert(!n1x_adsp_boot(&dsp, false));power_notification(0,7);
 assert(!dsp.power_queued && !dsp.power_work.pending && !power_calls);
 /* The IRQ routes a transaction ACK separately from firmware notifications. */
 reset();assert(!n1x_adsp_boot(&dsp, false));dsp.ipc_pending=true;dsp.ipc_token=0x3456;
 u8 *ack=(u8 *)shared_memory+ADSP_RX_OFFSET;memset(ack,0,ADSP_RX_BYTES);
 ack[16]=0x56;ack[17]=0x34;ack[21]=2;
 mailbox_memory[ADSP_OUT_STATUS/4]=1;
 assert(n1x_adsp_irq(0,&dsp)==IRQ_HANDLED && !dsp.ipc_pending && dsp.ipc_done.done);
 assert(!memcmp(dsp.ipc_reply.packet,ack,ADSP_RX_BYTES) && !dsp.ipc_poisoned);
 assert(!dsp.power_queued && dsp.ready.done);
 /* Playback notifications follow the actual IRQ slot-release path. */
 reset();assert(!n1x_adsp_boot(&dsp, false));
 dsp.primary_host_pcm=(struct n1x_adsp_pcm_config){.address=0xe0001000,.bytes=7680,.channels=2,.sample_bits=16};
 dsp.primary_period_enabled=true;dsp.primary_period=period_callback;dsp.primary_period_data=&dsp;
 u8 *event=(u8 *)shared_memory+ADSP_RX_OFFSET;memset(event,0,ADSP_RX_BYTES);
 event[18]=7;event[20]=1;event[22]=0x1b;n1x_adsp_ipc_put32(event+24,96);
 n1x_adsp_pcm_put64(event+0x30,0xe0001780);n1x_adsp_ipc_put32(event+0x74,5);
 mailbox_memory[ADSP_OUT_STATUS/4]=1;in_irq=1;
 assert(n1x_adsp_irq(0,&dsp)==IRQ_HANDLED && period_calls==1 && !period_error);in_irq=0;
 assert(!dsp.ipc_poisoned && dsp.primary_position.byte_offset==1920);
 event[21]=2;event[16]=1;dsp.ipc_pending=true;dsp.ipc_token=1;
 mailbox_memory[ADSP_OUT_STATUS/4]=1;in_irq=1;
 assert(n1x_adsp_irq(0,&dsp)==IRQ_HANDLED && period_calls==1 && dsp.ipc_done.done);in_irq=0;
 event[21]=0;n1x_adsp_pcm_put64(event+0x30,0xe0001001);
 mailbox_memory[ADSP_OUT_STATUS/4]=1;in_irq=1;
 assert(n1x_adsp_irq(0,&dsp)==IRQ_HANDLED && period_calls==2 && period_error==-ERANGE);in_irq=0;
 assert(dsp.primary_period_error==-ERANGE && !dsp.ipc_poisoned);
 /* Preserve order; only the worker performs the sleeping operation. */
 reset();assert(!n1x_adsp_boot(&dsp, false));power_notification(2,1);power_notification(2,2);
 assert(!power_calls);n1x_adsp_power_work(&dsp.power_work);
 assert(power_calls==2 && power_values[0]==1 && power_values[1]==2 && dsp.power_completed==2);
 /* A failed SSPM operation is terminal; later notifications cannot retry it. */
 reset();assert(!n1x_adsp_boot(&dsp, false));power_notification(2,3);power_notification(2,4);
 dsp.ipc_pending=true;dsp.ipc_token=1;
 power_reply=-EIO;n1x_adsp_power_work(&dsp.power_work);
 assert(power_calls==1 && power_value==3 && dsp.power_error==-EIO && !dsp.power_completed);
 assert(dsp.ipc_done.done && !dsp.ipc_pending && dsp.ipc_poisoned && dsp.ipc_error==-EIO);
 power_notification(2,5);n1x_adsp_power_work(&dsp.power_work);
 assert(power_calls==1 && dsp.power_queued==2 && dsp.power_error==-EIO);
 /* Overflow never overwrites a queued request or starts more power operations. */
 reset();assert(!n1x_adsp_boot(&dsp, false));dsp.ipc_pending=true;
 for(unsigned i=0;i<17;i++)power_notification(2,i);
 assert(dsp.power_queued==16 && dsp.power_requests.count==16 && dsp.power_error==-ENOSPC);
 assert(!dsp.ipc_pending && dsp.ipc_done.done && dsp.ipc_error==-ENOSPC && dsp.ipc_poisoned);
 n1x_adsp_power_work(&dsp.power_work);assert(!power_calls);
 reset();puts("DSP boot/IRQ, power requests, bounded queues and DMA lifetime tests passed");
}
'''
    with tempfile.TemporaryDirectory() as temporary:
        code, binary = Path(temporary) / 'test.c', Path(temporary) / 'test'
        code.write_text(harness)
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        '-Wno-unused-parameter', '-Wno-misleading-indentation',
                        '-fsanitize=address,undefined', '-g', '-I' + str(ROOT),
                        str(code), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
    test_remove(source)


if __name__ == '__main__':
    main()
