#!/usr/bin/env python3
"""Test the actual DSP primary-buffer registration and firmware-route checks."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent


def main():
    source = (ROOT / 'n1x_adsp.c').read_text()
    constants = source[source.index('#define ADSP_RX_OFFSET '):source.index('static bool enable_boot;')]
    state = source[source.index('struct n1x_adsp_target {'):
                   source.index('static int n1x_adsp_group_member(')]
    primary = source[source.index('static int n1x_adsp_primary_route('):
                     source.index('static ssize_t status_show(')]
    client = source[source.index('int n1x_adsp_prepare_primary(struct device *dev)'):
                    source.index('EXPORT_SYMBOL_GPL(n1x_adsp_prepare_primary);')]
    harness = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include "n1x_adsp_client.h"
#include "n1x_sroot_client.h"
typedef uint64_t u64;typedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;typedef uint64_t dma_addr_t;
typedef int spinlock_t;typedef int atomic_t;
struct device_driver {int unused;};
struct device {struct device_driver *driver;void *data;};
struct platform_driver {struct device_driver driver;};
struct mutex {int unused;};struct completion {bool done;};struct work_struct {int unused;};
struct fwnode_handle {unsigned index;};
#define DECLARE_KFIFO(name,type,size) struct {type data[size];} name
#define __iomem
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define READ_ONCE(x) (x)
#define DMA_BIT_MASK(n) ((1ULL<<(n))-1)
#define cpu_to_le64(x) ((__le64)(x))
static int atomic_read(atomic_t *p) {return *p;}
static struct platform_driver n1x_adsp_driver;
static struct device device,asd;

static struct fwnode_handle nodes[2]={{0},{1}};
static int device_locks,request_locks,lock_error,asd_refs,node_refs;
static unsigned property_reads,child_reads,transfers,barriers;
static int missing_asd,missing_node,property_error;
static u32 hw_version,endpoint_mask,routes[2];
static int failed_transfer,transfer_error,bad_echo;
static bool power_after_last;
static u8 memory[ADSP_MEMORY_PLACEHOLDER];
static void device_lock(struct device *dev) {assert(dev==&device && !device_locks++);}
static void device_unlock(struct device *dev) {assert(dev==&device && device_locks--==1);}
static void *dev_get_drvdata(struct device *dev) {assert(dev==&device);return dev->data;}
static int mutex_lock_interruptible(struct mutex *lock)
{(void)lock;if(lock_error)return lock_error;assert(!request_locks++);return 0;}
static void mutex_unlock(struct mutex *lock) {(void)lock;assert(request_locks--==1);}
static bool capture_fixture;
static struct device *n1x_adsp_find_device(struct device *consumer,const char *name)
{
 assert(consumer==&device && !strcmp(name,"NVDA9022"));
 if(missing_asd)return NULL;asd_refs++;return &asd;
}
static void put_device(struct device *dev) {assert(dev==&asd && asd_refs--==1 && !node_refs);}
static int device_property_read_u32(struct device *dev,const char *name,u32 *value)
{
 assert(dev==&asd && asd_refs==1);property_reads++;
 if(!strcmp(name,"acpi-asd-hw-ver")){if(property_error==1)return -EIO;*value=hw_version;}
 else {assert(!strcmp(name,"acpi-asd-endpoint-list"));if(property_error==2)return -EIO;*value=endpoint_mask;}
 return 0;
}
static struct fwnode_handle *device_get_named_child_node(struct device *dev,const char *name)
{
 unsigned i;assert(dev==&asd && asd_refs==1);child_reads++;
 if(capture_fixture){assert(!strcmp(name,"acpi-asd-microphone-subproperties"));i=0;}
 else if(!strcmp(name,"acpi-asd-speaker-subproperties"))i=0;
 else {assert(!strcmp(name,"acpi-asd-headphone-subproperties"));i=1;}
 if(missing_node==(int)i+1)return NULL;node_refs++;return &nodes[i];
}
static int fwnode_property_read_u32(struct fwnode_handle *node,const char *name,u32 *value)
{
 assert(asd_refs==1 && node_refs==1 && !strcmp(name,"acpi-asd-endpoint-path-config"));
 if(property_error==(int)node->index+3)return -EIO;*value=routes[node->index];return 0;
}
static void fwnode_handle_put(struct fwnode_handle *node)
{assert((node==&nodes[0] || node==&nodes[1]) && node_refs--==1);}
static void dma_wmb(void) {assert(device_locks==1 && request_locks==1);barriers++;}
''' .replace('ADSP_MEMORY_PLACEHOLDER', '4096 + 32') + constants + state + r'''
static struct n1x_adsp dsp;
static u64_PLACEHOLDER get64(const u8 *p)
{uint64_t v=0;for(unsigned i=0;i<8;i++)v|=(uint64_t)p[i]<<(8*i);return v;}
static void n1x_adsp_ipc_fail(struct n1x_adsp *context,int error)
{assert(context==&dsp);dsp.ipc_poisoned=true;dsp.ipc_error=error;}
static int n1x_adsp_transfer_locked(struct n1x_adsp *context,
 const struct n1x_adsp_ipc_request *request,struct n1x_adsp_ipc_reply *reply)
{
 const u16 commands[]={5,6,0x20a,0x20b};unsigned offset=transfers*1024;
 assert(context==&dsp && device_locks==1 && request_locks==1);
 assert(dsp.primary_attempted && !dsp.primary_ready && dsp.primary_error==-EINPROGRESS);
 assert(transfers<4 && barriers==transfers+1 && request->command==commands[transfers]);
 assert(request->channel==(capture_fixture?23:7) && request->data_mode==1 && request->ack_mode==1 && !request->token);
 assert(request->parameter1==32 && !request->parameter2 && request->payload);
 assert(get64(request->payload)==0xe0000000+offset);
 assert(get64(request->payload+8)==(uintptr_t)(memory+offset));
 assert(get64(request->payload+16)==1024 && !get64(request->payload+24));
 for(unsigned i=0;i<4096;i++)assert(memory[i]==0);
 for(unsigned i=4096;i<sizeof(memory);i++)assert(memory[i]==0xa5);
 transfers++;
 if(failed_transfer==(int)transfers)return transfer_error;
 memset(reply,0,sizeof(*reply));reply->packet[18]=bad_echo==1?8:(capture_fixture?23:7);
 reply->packet[21]=2;n1x_adsp_ipc_put16(reply->packet+22,request->command+(bad_echo==2));
 if(power_after_last && transfers==4)dsp.power_error=-EIO;
 return 0;
}
''' .replace('u64_PLACEHOLDER','uint64_t') + primary + client + r'''
static void reset(void)
{
 memset(&dsp,0,sizeof(dsp));memset(memory,0xa5,sizeof(memory));
 device.driver=&n1x_adsp_driver.driver;device.data=&dsp;dsp.dev=&device;
 dsp.target=&targets[2];dsp.dram=memory;dsp.dma=0xe0000000;
 dsp.published=true;dsp.boot_ready=true;dsp.loader.accepted=1;
 hw_version=1;endpoint_mask=0x1ff;routes[0]=routes[1]=2;
 device_locks=request_locks=asd_refs=node_refs=lock_error=0;
 property_reads=child_reads=transfers=barriers=0;
 missing_asd=missing_node=property_error=failed_transfer=bad_echo=0;
 transfer_error=-ETIMEDOUT;power_after_last=false;
 capture_fixture=false;
}
static void no_refs(void) {assert(!device_locks && !request_locks && !asd_refs && !node_refs);}
int main(void)
{
 reset();assert(!n1x_adsp_prepare_primary(&device));no_refs();
 assert(dsp.primary_ready && dsp.primary_completed==4 && !dsp.primary_error && transfers==4);
 memory[0]=0x11;assert(!n1x_adsp_prepare_primary(&device) && transfers==4 && memory[0]==0x11);
 dsp.power_error=-EIO;assert(n1x_adsp_prepare_primary(&device)==-ENOTRECOVERABLE && transfers==4);
 reset();routes[0]=routes[1]=3;dsp.target=&targets[0];
 assert(n1x_adsp_prepare_primary(&device)==-EOPNOTSUPP && !transfers && !dsp.primary_attempted);
 for(int stage=1;stage<=4;stage++){
  reset();failed_transfer=stage;assert(n1x_adsp_prepare_primary(&device)==-ETIMEDOUT);no_refs();
  assert(dsp.primary_attempted && !dsp.primary_ready && dsp.primary_error==-ETIMEDOUT);
  assert(transfers==(unsigned)stage && dsp.primary_completed==(unsigned)stage-1);
  assert(n1x_adsp_prepare_primary(&device)==-ETIMEDOUT && transfers==(unsigned)stage);
 }
 for(int echo=1;echo<=2;echo++){
  reset();bad_echo=echo;assert(n1x_adsp_prepare_primary(&device)==-EPROTO);no_refs();
  assert(dsp.ipc_poisoned && dsp.primary_error==-EPROTO && !dsp.primary_ready && transfers==1);
  assert(n1x_adsp_prepare_primary(&device)==-EPROTO && transfers==1);
 }
 for(int prop=1;prop<=4;prop++){
  reset();property_error=prop;assert(n1x_adsp_prepare_primary(&device)==-EIO);no_refs();
  assert(!transfers && !dsp.primary_attempted && memory[0]==0xa5);
 }
 for(int node=1;node<=2;node++){
  reset();missing_node=node;assert(n1x_adsp_prepare_primary(&device)==-ENODEV);no_refs();
  assert(!transfers && !dsp.primary_attempted);
 }
 for(unsigned guard=0;guard<16;guard++){
  reset();struct n1x_adsp_target target=targets[2];dsp.target=&target;
  if(guard==0)missing_asd=1;if(guard==1)hw_version=2;if(guard==2)endpoint_mask=1;
  if(guard==3)routes[0]=0;if(guard==4)routes[1]=3;if(guard==5)target.image_id=0xc0304;
  if(guard==6)dsp.dma=0xd0000000;if(guard==7)dsp.dma=0xffffff00;
  if(guard==8)target.dram_bytes=4095;if(guard==9)dsp.dram=NULL;
  if(guard==10)dsp.published=false;if(guard==11)dsp.boot_ready=false;
  if(guard==12)dsp.loader.accepted=0;if(guard==13)dsp.error=-EIO;
  if(guard==14)dsp.power_error=-EIO;if(guard==15)dsp.ipc_poisoned=true;
  assert(n1x_adsp_prepare_primary(&device)<0);no_refs();
  assert(!transfers && !barriers && !dsp.primary_attempted && memory[0]==0xa5);
 }
 reset();power_after_last=true;assert(n1x_adsp_prepare_primary(&device)==-EIO);
 assert(dsp.primary_completed==4 && !dsp.primary_ready && dsp.primary_error==-EIO);no_refs();
 reset();device.driver=NULL;assert(n1x_adsp_prepare_primary(&device)==-ENODEV);no_refs();
 reset();lock_error=-EINTR;assert(n1x_adsp_prepare_primary(&device)==-EINTR);no_refs();
 assert(!transfers && !property_reads && !dsp.primary_attempted);
 assert(n1x_adsp_prepare_primary(NULL)==-EINVAL);no_refs();
 for(unsigned route=0;route<5;route++) {
  reset();capture_fixture=dsp.capture=true;dsp.target=&targets[0];routes[0]=route;
  int ret=n1x_adsp_prepare_primary(&device);no_refs();
  if(route==3)assert(!ret && transfers==4 && dsp.primary_ready && child_reads==1);
  else assert(ret==-EOPNOTSUPP && !transfers && !dsp.primary_attempted);
 }
 reset();capture_fixture=dsp.capture=true;dsp.target=&targets[0];routes[0]=3;endpoint_mask=1;
 assert(n1x_adsp_prepare_primary(&device)==-EOPNOTSUPP && !transfers);no_refs();
 puts("DSP host registration: playback/capture firmware routes, bounded slices and terminal failures: PASS");
}
'''
    with tempfile.TemporaryDirectory(prefix='p16-dsp-primary-') as temporary:
        code, binary = Path(temporary) / 'test.c', Path(temporary) / 'test'
        code.write_text(harness)
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        '-Wno-misleading-indentation', '-fsanitize=address,undefined',
                        '-g', '-I' + str(ROOT), str(code), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=20)


if __name__ == '__main__':
    main()
