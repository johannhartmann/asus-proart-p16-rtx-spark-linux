#!/usr/bin/env python3
"""Test the actual primary PCM configuration and lifetime code with OS/RPC faults."""
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
    configure = source[source.index('static int n1x_adsp_primary_descriptor('):
                       source.index('EXPORT_SYMBOL_GPL(n1x_adsp_primary_commit);')]
    afe_header = re.sub(r'^#include.*\n', '', (HERE / 'mt8901-afe-sram.h').read_text(), flags=re.M)
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
typedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;typedef uint64_t u64;
typedef uint64_t dma_addr_t;typedef int spinlock_t;typedef int atomic_t;
#define __iomem
#define ERR_PTR(e) ((void *)(intptr_t)(e))
#define PTR_ERR(p) ((long)(intptr_t)(p))
#define IS_ERR(p) ((uintptr_t)(p)>=(uintptr_t)-4095)
#define IS_ERR_OR_NULL(p) (!(p)||IS_ERR(p))
#define DECLARE_KFIFO(name,type,size) struct {type entries[size];} name
#define READ_ONCE(x) (x)
#define spin_lock_irqsave(lock,flags) ((void)(lock),(flags)=0)
#define spin_unlock_irqrestore(lock,flags) ((void)(lock),(void)(flags))
#define synchronize_irq(irq) ((void)(irq))
#define U64_MAX UINT64_MAX
#define DMA_BIT_MASK(n) ((1ULL<<(n))-1)
#define GFP_KERNEL 0
#define EXPORT_SYMBOL_GPL(name)
#define cpu_to_le64(x) ((__le64)(x))
struct device_driver {int unused;};
struct device {struct device_driver *driver;void *data;};
struct platform_driver {struct device_driver driver;};
struct mutex {int unused;};struct completion {int unused;};struct work_struct {int unused;};
''' + afe_header + constants + state + r'''
struct mt8901_afe_sram_buffer {bool published;};
static struct mt8901_afe_sram_buffer lease,messages;
static struct n1x_adsp dsp;static struct n1x_adsp_target target;
static struct platform_driver n1x_adsp_driver;static struct device device;
static u8 memory[16U<<20],sram_memory[3840],ipc_memory[2048];
static struct mt8901_afe_sram_endpoint endpoint_data;
static pthread_mutex_t dev_mutex=PTHREAD_MUTEX_INITIALIZER,request_mutex=PTHREAD_MUTEX_INITIALIZER;
static unsigned dev_locked,request_locked,refs,allocations,symbol_refs,calls,publishes,ipc_publishes,barriers;
static unsigned fail_at,bad_at,bad_field,missing_symbol,ipc_fault,ipc_releases;
static int endpoint_error,publish_error,lock_error,afe_prepare_error;
static u64 ipc_afe_base;
static unsigned retirements;static unsigned afe_prepares,irq_prepares;static int irq_prepare_error;
static bool ring_filled;static unsigned late_power_at;
static u16 history[1024];static u8 tasks[1024];
static int atomic_read(atomic_t *p) {return *p;}
static void device_lock(struct device *dev)
{assert(dev==&device && !dev_locked);assert(!pthread_mutex_lock(&dev_mutex));dev_locked=1;}
static void device_unlock(struct device *dev)
{assert(dev==&device && dev_locked && !request_locked);dev_locked=0;assert(!pthread_mutex_unlock(&dev_mutex));}
static void *dev_get_drvdata(struct device *dev) {assert(dev==&device && dev_locked);return dev->data;}
static void mutex_lock(struct mutex *lock)
{assert(lock==&dsp.lock && dev_locked && !request_locked);assert(!pthread_mutex_lock(&request_mutex));request_locked=1;}
static int mutex_lock_interruptible(struct mutex *lock)
{if(lock_error)return lock_error;mutex_lock(lock);return 0;}
static void mutex_unlock(struct mutex *lock)
{assert(lock==&dsp.lock && dev_locked && request_locked);request_locked=0;assert(!pthread_mutex_unlock(&request_mutex));}
static struct device *get_device(struct device *dev) {assert(dev==&device && request_locked);refs++;return dev;}
static void put_device(struct device *dev) {assert(dev==&device && !dev_locked && refs);refs--;}
static void *kzalloc(size_t n,int flags)
{assert(n==sizeof(struct n1x_adsp_primary) && !flags && request_locked);void *p=calloc(1,n);assert(p);allocations++;return p;}
static void kfree(void *p) {assert(p && allocations);allocations--;free(p);}
static void dma_wmb(void) {assert(dev_locked && request_locked);barriers++;}
static void wmb(void) {assert(dev_locked && request_locked);barriers++;}
static void memcpy_toio(void *to,const void *from,size_t n)
{assert(to==ipc_memory && n==96 && messages.published && request_locked);memcpy(to,from,n);}
static int n1x_adsp_prepare_primary_locked(struct n1x_adsp *context)
{assert(context==&dsp && request_locked);return 0;}
static void n1x_adsp_ipc_fail(struct n1x_adsp *context,int err)
{assert(context==&dsp);dsp.ipc_poisoned=true;dsp.ipc_error=err;}
int mt8901_afe_sram_endpoint(struct mt8901_afe_sram_buffer *buffer,struct mt8901_afe_sram_endpoint *value,size_t bytes)
{assert(bytes==sizeof(*value) && buffer==&lease && dev_locked==request_locked);if(endpoint_error)return endpoint_error;
 *value=endpoint_data;value->published=lease.published||endpoint_data.published;return 0;}
int mt8901_afe_sram_publish(struct mt8901_afe_sram_buffer *buffer)
{assert(buffer==&lease && dev_locked && request_locked && calls==5 && tasks[4]==7 && history[4]==4);publishes++;
 if(publish_error)return publish_error;lease.published=true;return 0;}
struct mt8901_afe_sram_buffer *mt8901_afe_sram_reserve_ipc(struct mt8901_afe_sram_buffer *peer,size_t bytes)
{assert(peer==&lease && bytes==2048 && dev_locked && request_locked && calls==1);
 if(ipc_fault==1)return ERR_PTR(-ENOMEM);memset(ipc_memory,0,sizeof(ipc_memory));return &messages;}
int mt8901_afe_sram_view(struct mt8901_afe_sram_buffer *buffer,struct mt8901_afe_sram_view *value)
{assert(buffer==&messages);if(ipc_fault==2)return -EIO;
 *value=(struct mt8901_afe_sram_view){.area=ipc_memory,.bytes=2048,.cpu_address=0x1a6c1000,.afe_address=ipc_afe_base,.dsp_address=0x4e5c1000};
 if(ipc_fault==3)value->bytes--;if(ipc_fault==4)value->area=NULL;
 if(ipc_fault==5)value->afe_address=0x1a6c0000-1;if(ipc_fault==6)value->afe_address=0x1a6d4000-2047;return 0;}
int mt8901_afe_sram_publish_ipc(struct mt8901_afe_sram_buffer *buffer)
{assert(buffer==&messages && calls==1 && !buffer->published);ipc_publishes++;
 if(ipc_fault==7)return -EBUSY;buffer->published=true;return 0;}
int mt8901_afe_sram_release(struct mt8901_afe_sram_buffer *buffer)
{assert(buffer==&messages && !buffer->published);ipc_releases++;return 0;}
int mt8901_afe_sram_prepare(struct mt8901_afe_sram_buffer *buffer)
{assert(buffer==&lease && dev_locked && request_locked && lease.published);
 assert(dsp.primary_pcm_configured && !dsp.primary_pcm_prepared);afe_prepares++;return afe_prepare_error;}
int mt8901_afe_sram_prepare_irq(struct mt8901_afe_sram_buffer *buffer)
{assert(buffer==&lease && dev_locked && request_locked && lease.published);
 assert(afe_prepares==irq_prepares+1 && !dsp.primary_pcm_prepared);irq_prepares++;if(!irq_prepare_error)endpoint_data.irq_prepared=true;return irq_prepare_error;}
int mt8901_afe_sram_stop_irq(struct mt8901_afe_sram_buffer *buffer,unsigned core)
{assert(buffer==&lease && core==3 && dev_locked && request_locked);
 assert(history[calls-2]==0x10 && tasks[calls-2]==7 && history[calls-1]==0x10 && tasks[calls-1]==16);
 endpoint_data.irq_prepared=false;return 0;}
void mt8901_afe_sram_retire(struct mt8901_afe_sram_buffer *buffer)
{assert(buffer==&lease && lease.published && dsp.primary_sram==buffer && dsp.primary_owner);
 assert(dev_locked && request_locked && !dsp.primary_period && !dsp.primary_period_data);retirements++;}
int mt8901_afe_sram_allow_retention(struct mt8901_afe_sram_buffer *buffer)
{assert(buffer==&lease || buffer==&messages);assert(buffer->published);return 0;}
int mt8901_afe_sram_rebind(struct mt8901_afe_sram_buffer *buffer,struct snd_pcm_substream *substream)
{assert(buffer==&lease && substream==(void *)1 && buffer->published && retirements && dev_locked && request_locked);return 0;}
static void *get_symbol(const char *name)
{
 const char *names[]={"mt8901_afe_sram_endpoint","mt8901_afe_sram_publish","mt8901_afe_sram_reserve_ipc",
 "mt8901_afe_sram_view","mt8901_afe_sram_publish_ipc","mt8901_afe_sram_release","mt8901_afe_sram_prepare","mt8901_afe_sram_prepare_irq","mt8901_afe_sram_stop_irq","mt8901_afe_sram_retire","mt8901_afe_sram_rebind","mt8901_afe_sram_allow_retention"};
 void *functions[]={(void *)mt8901_afe_sram_endpoint,(void *)mt8901_afe_sram_publish,(void *)mt8901_afe_sram_reserve_ipc,
 (void *)mt8901_afe_sram_view,(void *)mt8901_afe_sram_publish_ipc,(void *)mt8901_afe_sram_release,(void *)mt8901_afe_sram_prepare,(void *)mt8901_afe_sram_prepare_irq,(void *)mt8901_afe_sram_stop_irq,(void *)mt8901_afe_sram_retire,(void *)mt8901_afe_sram_rebind,(void *)mt8901_afe_sram_allow_retention};
 for(unsigned i=0;i<12;i++)if(!strcmp(name,names[i])){if(missing_symbol==i+1)return NULL;symbol_refs++;return functions[i];}
 assert(0);return NULL;
}
static void put_symbol(const char *name) {(void)name;assert(symbol_refs);symbol_refs--;}
#define symbol_get(name) ((typeof(&name))get_symbol(#name))
#define symbol_put(name) put_symbol(#name)
static u64 get64(const u8 *p) {u64 value=0;for(unsigned i=0;i<8;i++)value|=(u64)p[i]<<(i*8);return value;}
static int n1x_adsp_transfer_locked(struct n1x_adsp *context,
 const struct n1x_adsp_ipc_request *request,struct n1x_adsp_ipc_reply *reply)
{
 assert(context==&dsp && dev_locked && request_locked && dsp.primary_task_active);
 assert((request->channel==7 || request->channel==16) && request->ack_mode==1 && !request->token && (request->parameter2==0 || (request->command==0x0f && request->channel==7 && request->parameter2==16)));
 assert(calls<1024);tasks[calls]=request->channel;history[calls++]=request->command;
 if(request->command==5 || request->command==6){
  unsigned offset=(request->command-5)*1024;
  assert(request->channel==16 && request->data_mode==1 && request->parameter1==32 && request->payload);
  assert(messages.published && dsp.processing_messages==&messages && !lease.published);
  assert(get64(request->payload)==ipc_afe_base+offset && get64(request->payload+8)==(uintptr_t)(ipc_memory+offset));
  assert(get64(request->payload+16)==1024 && !get64(request->payload+24));
 }else if(request->data_mode==1){
  bool preparing=request->command==0x203 || request->command==3;
  if(preparing)assert(afe_prepares>0);
  bool hardware=request->command==0x201 || (request->channel==16 && request->command==0x203);
  bool bridge=request->channel==16 && !hardware;
  assert(request->command==4 || request->command==0x201 || preparing);
  assert(dsp.primary_pcm_attempted && dsp.primary_pcm_configured==preparing && !dsp.primary_pcm_prepared);
  assert(request->parameter1==8 && request->payload);
  const u8 *packet=request->channel==7?memory:ipc_memory;
  assert(get64(request->payload)==(request->channel==7?dsp.dma:ipc_afe_base));
  u64 base=request->channel==7?0xe0001000:0x1a6c0000;unsigned bytes=request->channel==7?7680:3840;
  assert(get64(packet)==base && get64(packet+8)==base+bytes && get64(packet+16)==base && get64(packet+24)==base);
  assert(get64(packet+32)==bytes && !get64(packet+40));
  assert(n1x_adsp_ipc_get32(packet+48)==16 && n1x_adsp_ipc_get32(packet+52)==48000);
  assert(n1x_adsp_ipc_get32(packet+56)==2 && n1x_adsp_ipc_get32(packet+60)==1);
  assert(n1x_adsp_ipc_get32(packet+64)==(request->channel==7?1920:960) && n1x_adsp_ipc_get32(packet+68)==0xffffffff);
  assert(n1x_adsp_ipc_get32(packet+72)==480 && n1x_adsp_ipc_get32(packet+76)==(request->channel==7?4:2));
  assert(packet[80]==hardware && !packet[81] && !packet[82] && packet[83]==1);
  for(unsigned i=84;i<96;i++)assert(!packet[i]);
  for(unsigned i=96;i<4096;i++)assert(memory[i]==0xa5);
  for(unsigned i=96;i<2048;i++)assert(!ipc_memory[i]);
  for(unsigned i=4096;i<4096+7680;i++)assert(memory[i]==(ring_filled?0x5a:0));
  for(unsigned i=4096+7680;i<4096+7680+32;i++)assert(memory[i]==0xa5);
  assert(messages.published && dsp.processing_messages==&messages);
  if(hardware || bridge || preparing)assert(lease.published && dsp.primary_sram==&lease);
 }else{
  assert(request->command==1 || request->command==9 || request->command==2 || request->command==0x202 || request->command==0x0f || request->command==0x10);
  assert(request->parameter1==(request->command==0x202?1U:0U) && !request->payload);
  if(request->command==0x202)assert(request->channel==16);
 }
 if(fail_at==calls)return -ETIMEDOUT;
 memset(reply,0,sizeof(*reply));reply->packet[18]=bad_at==calls && bad_field==1?8:request->channel;
 reply->packet[21]=2;n1x_adsp_ipc_put16(reply->packet+22,request->command+(bad_at==calls && bad_field==2));
 if(late_power_at==calls){dsp.power_error=-EIO;return -EIO;}return 0;
}
static bool auto_boot;
static int n1x_adsp_boot(struct n1x_adsp *dsp,bool kernel_client) {(void)dsp;(void)kernel_client;assert(0);return -EIO;}
''' + lifecycle + configure + r'''
static const struct n1x_adsp_primary_pcm_params defaults={48000,2,16,480,4};
static void reset(void)
{
 assert(!dev_locked && !request_locked && !refs && !allocations && !symbol_refs);
 memset(&dsp,0,sizeof(dsp));memset(&lease,0,sizeof(lease));memset(&messages,0,sizeof(messages));
 memset(memory,0xa5,sizeof(memory));memset(ipc_memory,0xa5,sizeof(ipc_memory));
 target=targets[2];dsp.target=&target;dsp.dev=&device;dsp.dram=memory;dsp.dma=0xe0000000;
 device.driver=&n1x_adsp_driver.driver;device.data=&dsp;
 endpoint_data=(struct mt8901_afe_sram_endpoint){.abi_version=2,
  .memory={.area=sram_memory,.bytes=3840,.cpu_address=0x1a6c0000,.afe_address=0x1a6c0000,.dsp_address=0x4e5c0000},
  .rate=48000,.channels=2,.sample_bits=16,.period_frames=480,.periods=2};
 ipc_afe_base=0x1a6c1000;calls=publishes=ipc_publishes=barriers=fail_at=bad_at=bad_field=missing_symbol=ipc_fault=ipc_releases=0;
 endpoint_error=publish_error=lock_error=afe_prepare_error=0;afe_prepares=irq_prepares=0;irq_prepare_error=0;ring_filled=false;late_power_at=0;retirements=0;
}
static void closed(void) {assert(retirements==(unsigned)lease.published && !dsp.primary_retire);assert(!refs && !allocations && !symbol_refs && !dev_locked && !request_locked);}
static struct n1x_adsp_primary *open_primary(void)
{struct n1x_adsp_primary *p=n1x_adsp_primary_open(&device);assert(!IS_ERR(p) && calls==1);return p;}
static void configure(struct n1x_adsp_primary *p)
{struct mt8901_afe_sram_buffer *buffer=&lease;assert(!n1x_adsp_primary_configure(p,&defaults,&buffer) && !buffer && calls==7);
 assert(dsp.primary_pcm_configured && dsp.processing_active && dsp.processing_messages==&messages && !symbol_refs);}
int main(void)
{
 reset();ipc_afe_base=0x30001000;struct n1x_adsp_primary *relocated=open_primary();
 configure(relocated);assert(dsp.processing_address==ipc_afe_base);
 assert(!n1x_adsp_primary_close(relocated));closed();
 reset();struct n1x_adsp_primary *p=open_primary();configure(p);
 memset(memory+4096,0x5a,7680);ring_filled=true;
 assert(!n1x_adsp_primary_prepare_pcm(p) && calls==11 && dsp.primary_pcm_prepared && !symbol_refs);
 assert(!n1x_adsp_primary_prepare_pcm(p) && calls==11 && irq_prepares==1 && !symbol_refs);
 assert(dsp.primary_read_address==0xe0001000 && !dsp.primary_write_publications);
 assert(!n1x_adsp_primary_commit(p,3840) && calls==11 && dsp.primary_write_publications==1);
 assert(dsp.primary_write_counter==1 && get64(memory+24)==0xe0001f00);
 for(unsigned i=4096;i<4096+7680;i++)assert(memory[i]==0x5a);
 dsp.primary_period_error=-ERANGE;
 assert(n1x_adsp_primary_prepare_pcm(p)==-ERANGE && calls==11 && !symbol_refs);
 dsp.primary_period_error=0;
 struct n1x_adsp_primary_pcm_view view={0};assert(!n1x_adsp_primary_pcm_view(p,&view));
 assert(view.area==memory+4096 && view.bytes==7680);
 assert(!n1x_adsp_primary_close(p) && calls==16 && !dsp.processing_active && !dsp.primary_pcm_prepared);closed();
 const u16 expected[]={1,5,6,1,4,0x201,4,0x203,3,0x203,3,9,2,9,0x202,2};
 const u8 expected_tasks[]={7,16,16,16,7,16,16,16,16,7,7,7,7,16,16,16};
 assert(!memcmp(history,expected,sizeof(expected)) && !memcmp(tasks,expected_tasks,sizeof(expected_tasks)));
 assert(messages.published && lease.published && dsp.processing_messages==&messages && !ipc_releases);
 assert(!dsp.primary_pcm_attempted && !dsp.primary_owner);closed();

 reset();p=open_primary();configure(p);
 for(unsigned cycle=0;cycle<32;cycle++) {
  assert(!n1x_adsp_primary_prepare_pcm(p) && calls==11+cycle*8 && dsp.primary_pcm_prepared);
  assert(!dsp.primary_stopped && !dsp.primary_start_attempted && !dsp.primary_write_publications);
  assert(!n1x_adsp_primary_commit(p,3840));
  dsp.primary_period=(void *)1; /* This harness injects no receive IRQ. */
  assert(!n1x_adsp_primary_start(p) && calls==13+cycle*8 && dsp.primary_running);
  assert(!n1x_adsp_primary_stop(p) && calls==15+cycle*8 && dsp.primary_stopped);
  assert(!dsp.primary_pcm_prepared && !dsp.primary_period_enabled && !dsp.primary_period);
  assert(!n1x_adsp_primary_stop(p) && calls==15+cycle*8);
 }
 assert(afe_prepares==32 && irq_prepares==32);
 assert(!n1x_adsp_primary_close(p));closed();

 reset();p=open_primary();configure(p);assert(!n1x_adsp_primary_close(p));
 for(unsigned cycle=0;cycle<32;cycle++) {
  unsigned before=calls;retirements=0;
  p=n1x_adsp_primary_open(&device);assert(!IS_ERR(p) && calls==before+1);
  retirements=1; /* Confirms the prior borrowed substream was retired. */
  assert(!n1x_adsp_primary_rebind(p,(void *)1));
  struct mt8901_afe_sram_buffer *retained=NULL;
  assert(!n1x_adsp_primary_configure(p,&defaults,&retained) && !retained && calls==before+5);
  assert(ipc_publishes==1 && publishes==1 && !ipc_releases);
  assert(!n1x_adsp_primary_prepare_pcm(p));
  assert(!n1x_adsp_primary_commit(p,3840));dsp.primary_period=(void *)1;
  assert(!n1x_adsp_primary_start(p) && !n1x_adsp_primary_stop(p));
  retirements=0;assert(!n1x_adsp_primary_close(p));closed();
  assert(dsp.primary_sram==&lease && dsp.processing_messages==&messages && lease.published && messages.published);
 }
 for(unsigned fault=0;fault<29;fault++){
  reset();p=open_primary();struct n1x_adsp_primary_pcm_params params=defaults;struct mt8901_afe_sram_buffer *buffer=&lease;
  switch(fault){
  case 0:missing_symbol=1;break;case 1:missing_symbol=2;break;case 2:endpoint_error=-EBUSY;break;
  case 3:endpoint_data.abi_version=3;break;case 4:endpoint_data.memory.area=NULL;break;
  case 5:endpoint_data.published=true;break;case 6:params.rate=44100;break;
  case 7:params.sample_bits=32;break;case 8:params.period_frames=0;break;
  case 9:params.periods=1;break;case 10:params.period_frames=0x80000000;break;
  case 11:params.period_frames=0x100000;break;case 12:endpoint_data.periods=1;break;
  case 13:endpoint_data.memory.bytes++;break;case 14:endpoint_data.memif=16;break;
  case 15:lock_error=-EINTR;break;case 16:device.driver=NULL;break;
  case 17:dsp.primary_owner=NULL;break;case 18:dsp.primary_task_active=false;break;
  case 19:dsp.dram=NULL;break;case 20:target.dram_bytes=4096;break;
  case 21:endpoint_data.memory.bytes=(1ULL<<32)+3840;break;
  case 22:params.period_frames=params.periods=0xffffffff;break;case 23:target.image_id=0xc0304;break;case 24:missing_symbol=7;break;case 25:endpoint_data.abi_version=1;break;case 26:missing_symbol=8;break;case 27:missing_symbol=9;break;case 28:missing_symbol=10;break;}
  assert(n1x_adsp_primary_configure(p,&params,&buffer)<0 && buffer==&lease && calls==1 && !symbol_refs);
  assert(!lease.published && !messages.published && !dsp.primary_pcm_attempted);
  for(unsigned i=0;i<4096+7680+32;i++)assert(memory[i]==0xa5);
  lock_error=0;device.driver=&n1x_adsp_driver.driver;dsp.primary_owner=p;dsp.primary_task_active=true;
  assert(!n1x_adsp_primary_close(p) && calls==3);closed();
 }
 for(unsigned fault=0;fault<11;fault++){
  reset();p=open_primary();struct mt8901_afe_sram_buffer *buffer=&lease;
  if(fault<4)missing_symbol=fault+3;else ipc_fault=fault-3;
  assert(n1x_adsp_primary_configure(p,&defaults,&buffer)<0 && buffer==&lease && calls==1 && !symbol_refs);
  assert(!messages.published && !lease.published && !dsp.primary_pcm_attempted);
  assert(ipc_releases==(fault>=5?1U:0U));
  assert(!n1x_adsp_primary_close(p) && calls==3);closed();
 }
 for(unsigned stage=2;stage<=11;stage++)for(unsigned echo=0;echo<=2;echo++){
  reset();p=open_primary();struct mt8901_afe_sram_buffer *buffer=&lease;
  if(stage>=8)configure(p);
  int expected_error=echo?-EPROTO:-ETIMEDOUT;
  if(echo){bad_at=stage;bad_field=echo;}else fail_at=stage;
  int error=stage>=8?n1x_adsp_primary_prepare_pcm(p):n1x_adsp_primary_configure(p,&defaults,&buffer);
  assert(error==expected_error && calls==stage && !symbol_refs && !dsp.primary_pcm_prepared);
  assert(messages.published && dsp.processing_messages==&messages && !ipc_releases);
  assert(lease.published==(stage>=6) && dsp.primary_task_error==expected_error);
  struct n1x_adsp_primary_pcm_view before;memset(&before,0xa5,sizeof(before));view=before;
  assert(n1x_adsp_primary_pcm_view(p,&view)==expected_error && !memcmp(&view,&before,sizeof(view)));
  assert(n1x_adsp_primary_close(p)==expected_error && calls==stage);closed();
  assert(PTR_ERR(n1x_adsp_primary_open(&device))==expected_error && calls==stage);closed();
 }
 for(unsigned fault=0;fault<20;fault++){
  reset();p=open_primary();configure(p);
  switch(fault){
  case 0:missing_symbol=1;break;case 1:endpoint_error=-EBUSY;break;
  case 2:device.driver=NULL;break;case 3:lock_error=-EINTR;break;
  case 4:dsp.primary_owner=NULL;break;case 5:dsp.primary_task_active=false;break;
  case 6:dsp.primary_pcm_configured=false;break;case 7:dsp.primary_sram=NULL;break;
  case 8:dsp.primary_task_error=-EIO;break;case 9:dsp.ipc_poisoned=true;break;
  case 10:dsp.power_error=-EIO;break;case 11:endpoint_data.abi_version=3;break;
  case 12:lease.published=false;break;case 13:dsp.primary_host_pcm.periods=1;break;
  case 14:dsp.processing_active=false;break;case 15:dsp.processing_messages=NULL;break;
  case 16:dsp.processing_area=NULL;break;case 17:missing_symbol=7;break;case 18:endpoint_data.abi_version=1;break;case 19:missing_symbol=8;break;
  }
  u8 before[96];memcpy(before,memory,sizeof(before));
  assert(n1x_adsp_primary_prepare_pcm(p)<0 && calls==7 && !symbol_refs && !dsp.primary_pcm_prepared);
  assert(!memcmp(before,memory,sizeof(before)));
  missing_symbol=0;endpoint_error=lock_error=0;device.driver=&n1x_adsp_driver.driver;
  dsp.primary_owner=p;dsp.primary_task_active=dsp.primary_pcm_configured=true;
  dsp.processing_active=true;dsp.processing_messages=&messages;dsp.processing_area=ipc_memory;
  dsp.primary_sram=&lease;dsp.primary_task_error=0;dsp.ipc_poisoned=false;dsp.power_error=0;lease.published=true;
  assert(!n1x_adsp_primary_close(p) && calls==12);closed();
 }
 for(unsigned fault=0;fault<2;fault++){
  reset();p=open_primary();configure(p);afe_prepare_error=fault?-ETIMEDOUT:-EIO;
  assert(n1x_adsp_primary_prepare_pcm(p)==afe_prepare_error && calls==7 && afe_prepares==1 && !symbol_refs);
  int error=afe_prepare_error;afe_prepare_error=0;
  assert(n1x_adsp_primary_prepare_pcm(p)==error && calls==7 && afe_prepares==1 && !symbol_refs);
  assert(n1x_adsp_primary_close(p)==error && calls>=7 && (calls-7)%8==0 && lease.published && messages.published);closed();
 }
 for(unsigned fault=0;fault<2;fault++){
  reset();p=open_primary();configure(p);irq_prepare_error=fault?-ETIMEDOUT:-EIO;
  assert(n1x_adsp_primary_prepare_pcm(p)==irq_prepare_error && calls==11 && irq_prepares==1 && !symbol_refs);
  int error=irq_prepare_error;irq_prepare_error=0;
  assert(n1x_adsp_primary_prepare_pcm(p)==error && calls==11 && irq_prepares==1 && !symbol_refs);
  assert(n1x_adsp_primary_close(p)==error && calls>=11 && (calls-11)%8==0 && lease.published && messages.published);closed();
 }
 for(unsigned stage=12;stage<=16;stage++)for(unsigned echo=0;echo<=2;echo++){
  reset();p=open_primary();configure(p);assert(!n1x_adsp_primary_prepare_pcm(p));
  int expected_error=echo?-EPROTO:-ETIMEDOUT;
  if(echo){bad_at=stage;bad_field=echo;}else fail_at=stage;
  assert(n1x_adsp_primary_close(p)==expected_error && calls==stage && messages.published && lease.published);closed();
 }
 reset();p=open_primary();struct mt8901_afe_sram_buffer *buffer=&lease;publish_error=-EBUSY;
 assert(n1x_adsp_primary_configure(p,&defaults,&buffer)==-EBUSY && buffer==&lease && calls==5 && !lease.published);
 assert(messages.published && !ipc_releases && n1x_adsp_primary_close(p)==-EBUSY && calls==5);closed();
 for(unsigned stage=2;stage<=11;stage++){
  reset();p=open_primary();buffer=&lease;if(stage>=8)configure(p);late_power_at=stage;
  int error=stage>=8?n1x_adsp_primary_prepare_pcm(p):n1x_adsp_primary_configure(p,&defaults,&buffer);
  assert(error==-EIO && calls==stage && messages.published && !ipc_releases && !symbol_refs);
  assert(n1x_adsp_primary_close(p)==-EIO && calls==stage);closed();
 }
 assert(n1x_adsp_primary_configure(NULL,&defaults,&buffer)==-EINVAL);
 assert(n1x_adsp_primary_prepare_pcm(NULL)==-EINVAL && n1x_adsp_primary_pcm_view(NULL,NULL)==-EINVAL);
 puts("DSP PCM pipeline: tasks 7/16, SRAM message ownership, HWPARAM/PREPARE/close vectors and terminal faults: PASS");
 return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='dsp-pcm-service-') as directory:
        directory = Path(directory)
        source, binary = directory / 'service.c', directory / 'service'
        source.write_text(code)
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        '-Wno-misleading-indentation', '-fsanitize=address,undefined',
                        '-pthread', '-g', '-I', str(HERE), str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
