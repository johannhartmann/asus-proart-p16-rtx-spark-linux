#!/usr/bin/env python3
"""Exercise the AFE SRAM owner and patched suspend callback with mocked OS edges."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def patched_pcm():
    """Replay the packaged PCM delta without a local prepared kernel tree."""
    name = 'sound/soc/mediatek/mt8901/mt8901-afe-pcm.c'
    heading = f'diff --git a/{name} b/{name}\n'
    sections = re.split(r'(?=^diff --git )',
                        (ROOT / 'kernel/1030-n1x-audio.patch').read_text(), flags=re.M)
    prerequisite = ''.join(section for section in sections if section.startswith(heading))
    expected = json.loads((HERE / 'base.json').read_text())['sha256'][name]
    with tempfile.TemporaryDirectory(prefix='afe-pcm-replay-') as directory:
        subprocess.run(['patch', '--batch', '--fuzz=0', '-p1'],
                       input=prerequisite, text=True, cwd=directory,
                       check=True, stdout=subprocess.PIPE)
        path = Path(directory) / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Audio prerequisite differs from the pinned PCM base')
        subprocess.run(['git', 'apply', '--include=' + name,
                        str(ROOT / 'kernel/p16-afe-sram.patch')],
                       cwd=directory, check=True)
        return path.read_text()


def main():
    pcm = patched_pcm()
    suspend = pcm[pcm.index('static int mt8901_afe_runtime_suspend('):
                  pcm.index('static int mt8901_afe_runtime_resume(')]
    domain = pcm[pcm.index('int mt8901_afe_sram_domain('):pcm.index('static int mt8901_afe_fe_trigger(')]
    header = re.sub(r'^#include.*\n', '', (HERE / 'mt8901-afe-sram.h').read_text(), flags=re.M)
    owner = re.sub(r'^#include.*\n', '', (HERE / 'mt8901-afe-sram.c').read_text(), flags=re.M)
    code = r'''
#define _DEFAULT_SOURCE
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>
typedef uint8_t u8;typedef uint32_t u32;typedef uint64_t u64;typedef _Atomic int atomic_t;
#define atomic_read(p) atomic_load(p)
#define atomic_set(p,n) atomic_store(p,n)
#define atomic_inc(p) atomic_fetch_add(p,1)
#define atomic_dec(p) atomic_fetch_sub(p,1)
#define __iomem
#define __force
#define GFP_KERNEL 0
#define NUMA_NO_NODE -1
#define THIS_MODULE ((void *)1)
#define AUDIO_PD 5
#define U32_MAX UINT32_MAX
#define BIT(n) (1U<<(n))
#define AFE_IRQ0_MCU_CFG0 0x9d40
#define AFE_IRQ_MCU_EN 0x9d00
#define AFE_IRQ_MCU_DSP_EN 0x9d04
#define AFE_IRQ_MCU_DSP3_EN 0xa000
#define AFE_DL0_CON0 0x4460
#define AFE_DL1_CON0 0x4490
#define AFE_VUL1_CON0 0x4db0
#define DL_ON_SFT 28
#define MT8901_AFE_MEMIF_DL0 0
#define MT8901_AFE_MEMIF_DL1 1
#define MT8901_AFE_MEMIF_UL1 8
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define IS_ALIGNED(n,a) (!((n)&((a)-1)))
#define ERR_PTR(e) ((void *)(intptr_t)(e))
#define PTR_ERR(p) ((long)(intptr_t)(p))
#define IS_ERR(p) ((uintptr_t)(p)>=(uintptr_t)-4095)
#define IS_ERR_OR_NULL(p) (!(p)||IS_ERR(p))
#define EXPORT_SYMBOL_GPL(name)
struct device_driver {int unused;};struct platform_driver {struct device_driver driver;};
struct device {struct device_driver *driver;void *data;};
struct fwnode_handle {int unused;};
struct mt8901_afe_sram;
struct mt8901_afe_private {struct mt8901_afe_sram *sram;int pm_runtime_bypass_reg_ctl;void *dai_priv[16];};
struct mtk_dai_memif_priv {unsigned fs_timing,domain,minlen,maxlen;};
struct snd_pcm_substream;
struct mtk_base_memif_data {int reg_ofs_base,reg_ofs_end,reg_ofs_base_msb,reg_ofs_end_msb,msb_reg,msb_end_reg,enable_reg,enable_shift;};
struct mtk_base_afe_memif {struct snd_pcm_substream *substream;int irq_usage;
 const struct mtk_base_memif_data *data;unsigned char *dma_area;u64 dma_addr;size_t dma_bytes;};
struct mtk_base_irq_data {int id,irq_cnt_reg,irq_cnt_shift;u32 irq_cnt_maskbit;
 int irq_fs_reg,irq_fs_shift;u32 irq_fs_maskbit;int irq_en_reg,irq_en_shift,irq_domain_reg,irq_domain_shift;u32 irq_domain_maskbit;
 int irq_clr_reg,irq_clr_shift,irq_mask_reg,irq_mask_shift;};
struct mtk_base_afe_irq {bool irq_occupyed;const struct mtk_base_irq_data *irq_data;};
struct mtk_base_afe {struct device *dev;struct mt8901_afe_private *platform_priv;void *regmap;
 int (*get_memif_pbuf_size)(struct snd_pcm_substream *);
 int (*irq_fs)(struct snd_pcm_substream *,unsigned);
 struct mtk_base_afe_memif memif[16];struct mtk_base_afe_irq irqs[22];int memif_size,irqs_size;};
struct snd_soc_dai {struct device *dev;int id;void *data;};
struct snd_soc_card {struct device *dev;void *snd_card;bool instantiated;};
struct snd_pcm {void *card;};
struct snd_soc_pcm_runtime {struct snd_soc_dai *cpu;struct snd_soc_card *card;};
struct snd_pcm_runtime {u32 rate,channels,sample_bits,periods;u64 period_size;bool running;};
struct snd_pcm_substream {struct snd_pcm *pcm;int stream;struct snd_pcm_runtime *runtime;struct snd_soc_pcm_runtime *rtd;};
#define MT8901_AFE_MEMIF_NUM 16
#define MT8901_AFE_MEMIF_UL_START 7
#define SNDRV_PCM_STREAM_PLAYBACK 0
#define SNDRV_PCM_STREAM_CAPTURE 1
struct resource {unsigned long start,end;const char *name;};
#define DEFINE_RES_MEM(base,bytes) { .start=(base),.end=(base)+(bytes)-1 }
struct gen_pool {unsigned long base;unsigned char used[5120];};
''' + header + r'''
static struct platform_driver mt8901_afe_pcm_driver;
static struct device device,card_device;
static struct snd_soc_card card;
static struct snd_pcm pcm;
static unsigned card_refs;
static struct mt8901_afe_private private;
static struct mtk_base_afe afe;
static struct snd_soc_dai dai;
static struct snd_soc_pcm_runtime rtd;
static struct snd_pcm_runtime runtime;
static struct snd_pcm_substream stream;
static struct fwnode_handle node;
static pthread_mutex_t lock=PTHREAD_MUTEX_INITIALIZER;
static _Thread_local unsigned locked;
static atomic_uint allocations;
static atomic_uint module_refs,device_refs;
static unsigned pm_refs,pools,node_refs,io_bytes,barriers,hardware_calls;
static unsigned program_calls,program_fail_at,expected_offset,expected_irq;
static struct mtk_base_memif_data memif_data;
static struct mtk_base_irq_data irq_data;static struct mtk_dai_memif_priv memif_clock;
static unsigned irq_updates,irq_fail_at,stop_calls,stop_fail_step;
static bool irq_stopping,engine_starting;static u32 mcu_word,dsp_word,clear_read,memif_word;
static u32 cfg_word,counter_word;static int irq_read_error,fs_value;
static unsigned engine_updates,engine_fail_at;
static unsigned managed_count;
static void *managed[8];static void (*destructors[8])(void *);
static int init_fault,property_fault,property_changed,datapath_error;
static bool property_present,node_present,module_alive,pm_enabled,pm_active,allocation_fails;
static int resume_error;
static unsigned char *mapping;
static u32 version,count,properties[4];
static int mt8901_afe_runtime_suspend(struct device *dev);
static void device_lock(struct device *dev)
{assert(dev==&device && !locked);assert(!pthread_mutex_lock(&lock));locked=1;}
static void device_unlock(struct device *dev)
{assert(dev==&device && locked);locked=0;assert(!pthread_mutex_unlock(&lock));}
static void *dev_get_drvdata(struct device *dev) {assert(dev==&device);return dev->data;}
static void *snd_soc_dai_get_drvdata(struct snd_soc_dai *d) {return d->data;}
static struct snd_soc_pcm_runtime *snd_soc_substream_to_rtd(struct snd_pcm_substream *s) {return s->rtd;}
static bool snd_soc_card_is_instantiated(struct snd_soc_card *c) {return c && c->instantiated;}
static struct snd_soc_dai *snd_soc_rtd_to_cpu(struct snd_soc_pcm_runtime *r,unsigned i) {assert(!i);return r->cpu;}
static bool snd_pcm_running(struct snd_pcm_substream *s) {return s->runtime->running;}
static int mtk_afe_fe_startup(struct snd_pcm_substream *s,struct snd_soc_dai *d)
{assert(locked && d->id>=0 && d->id<16);afe.memif[d->id].substream=s;return 0;}
static int regmap_write(void *map,int reg,u32 value)
{assert(locked && pm_refs && pm_active && map==afe.regmap && program_calls<4);
 const int regs[]={0x10,0x14,0x18,0x1c};
 const u32 values[]={0x1a6c0000+expected_offset,0x1a6c0000+expected_offset+3839,0,0};
 assert(reg==regs[program_calls] && value==values[program_calls]);
 program_calls++;return program_calls==program_fail_at?-EIO:0;}
static unsigned engine_memif;
static bool moving;static unsigned move_reads,move_fail;static u32 move_words[4];
static int regmap_read(void *map,int reg,u32 *value)
{if(moving){
 const int regs[]={0x9d40,AFE_DL0_CON0,0x9d48,AFE_DL1_CON0};
 assert(locked && map==afe.regmap && move_reads<4 && reg==regs[move_reads]);
 *value=move_words[move_reads++];return move_reads==move_fail?-EIO:0;
 }if(irq_stopping){
 assert(locked && pm_refs && pm_active && map==afe.regmap && reg==0x9d44+(int)expected_irq*8 && stop_calls==2);
 stop_calls++;if(stop_fail_step==stop_calls)return -EIO;*value=clear_read=counter_word;return 0;
 }assert(locked && pm_refs && pm_active && map==afe.regmap && reg==0x9d40+(int)expected_irq*8);
 if(irq_read_error)return irq_read_error;*value=cfg_word;return 0;}
static int regmap_update_bits(void *map,int reg,u32 mask,u32 value)
{if(engine_starting){
 assert(locked && pm_refs && pm_active && map==afe.regmap && engine_updates<7);
 int cfg=AFE_IRQ0_MCU_CFG0+expected_irq*8;int target=engine_memif==8?AFE_IRQ_MCU_DSP_EN:AFE_IRQ_MCU_DSP3_EN;int enable=engine_memif==8?AFE_VUL1_CON0:AFE_DL0_CON0;
 const int regs[]={cfg+4,cfg,cfg,AFE_IRQ_MCU_EN,target,enable,cfg};
 const u32 masks[]={0xffffff,0x1f<<4,7<<9,BIT(expected_irq),BIT(expected_irq),BIT(28),BIT(0)},values[]={480,10<<4,1<<9,0,BIT(expected_irq),BIT(28),BIT(0)};
 assert(reg==regs[engine_updates] && mask==masks[engine_updates] && value==values[engine_updates]);
 u32 *word=reg==AFE_IRQ_MCU_EN?&mcu_word:reg==target?&dsp_word:reg==enable?&memif_word:reg==cfg+4?&counter_word:&cfg_word;
 *word=(*word&~mask)|(value&mask);engine_updates++;return engine_updates==engine_fail_at?-EIO:0;
 }if(irq_stopping){
 assert(locked && pm_refs && pm_active && map==afe.regmap && stop_calls<6 && stop_calls!=2);
 int enable=engine_memif==8?AFE_VUL1_CON0:AFE_DL0_CON0;
 const int regs[]={enable,0x9d40+(int)expected_irq*8,0,0x9d44+(int)expected_irq*8,0x9d00,engine_memif==8?0x9d04:0xa000};
 const u32 masks[]={BIT(28),1,0,BIT(31),BIT(expected_irq),BIT(expected_irq)};const u32 values[]={0,0,0,~clear_read&BIT(31),0,0};
 assert(reg==regs[stop_calls] && mask==masks[stop_calls] && value==values[stop_calls]);
 u32 *word=reg==enable?&memif_word:reg==0x9d40+(int)expected_irq*8?&cfg_word:reg==0x9d44+(int)expected_irq*8?&counter_word:reg==0x9d00?&mcu_word:&dsp_word;
 *word=(*word&~mask)|(value&mask);stop_calls++;return stop_calls==stop_fail_step?-EIO:0;
 }assert(locked && pm_refs && pm_active && map==afe.regmap && program_calls==4 && irq_updates<3);
 const int regs[]={0x9d44+(int)expected_irq*8,0x9d40+(int)expected_irq*8,0x9d40+(int)expected_irq*8};const u32 masks[]={0xffffff,0x1f<<4,7<<9};
 const u32 values[]={480,10<<4,1<<9};
 assert(reg==regs[irq_updates] && mask==masks[irq_updates] && value==values[irq_updates]);
 u32 *word=reg==0x9d40+(int)expected_irq*8?&cfg_word:&counter_word;*word=(*word&~mask)|(value&mask);
 irq_updates++;return irq_updates==irq_fail_at?-EIO:0;}
static int irq_fs(struct snd_pcm_substream *s,unsigned rate)
{assert(s==&stream && rate==s->runtime->rate && locked);return fs_value;}
static int unsupported_pbuf(struct snd_pcm_substream *s) {(void)s;return 0;}
static bool device_property_present(struct device *dev,const char *key)
{assert(dev==&device && !strcmp(key,"acpi-asd-sram-resource-list"));return property_present;}
static int device_property_read_u32(struct device *dev,const char *key,u32 *value)
{assert(dev==&device);if(property_fault==1)return -EIO;
 if(!strcmp(key,"acpi-asd-hw-ver"))*value=version;
 else {assert(!strcmp(key,"acpi-asd-sram-resource-list"));*value=count;}return 0;}
static struct fwnode_handle *device_get_named_child_node(struct device *dev,const char *key)
{assert(dev==&device && !strcmp(key,"acpi-asd-afe-sram-subproperties"));
 if(!node_present)return NULL;node_refs++;return &node;}
static int fwnode_property_read_u32(struct fwnode_handle *n,const char *key,u32 *value)
{
 static const char *keys[]={"acpi-asd-sram-size","acpi-asd-sram-cpu-view",
 "acpi-asd-sram-vad-view","acpi-asd-sram-adsp-view"};
 assert(n==&node && node_refs==1);unsigned i;for(i=0;i<4;i++)if(!strcmp(key,keys[i]))break;
 assert(i<4);if(property_fault==(int)i+2)return -EIO;
 *value=properties[i]+(property_changed==(int)i+1);return 0;
}
static void fwnode_handle_put(struct fwnode_handle *n) {assert(n==&node && node_refs==1);node_refs--;}
static void manage(void *p,void (*destructor)(void *))
{assert(managed_count<8);managed[managed_count]=p;destructors[managed_count++]=destructor;}
static void cleanup(void)
{while(managed_count){managed_count--;destructors[managed_count](managed[managed_count]);}}
static void *devres_open_group(struct device *dev,void *id,int flags)
{assert(dev==&device && !id && !flags && !managed_count);return init_fault==1?NULL:(void *)2;}
static void devres_close_group(struct device *dev,void *id) {assert(dev==&device && id==(void *)2);}
static void devres_release_group(struct device *dev,void *id)
{assert(dev==&device && id==(void *)2);cleanup();}
static void *devm_kzalloc(struct device *dev,size_t n,int flags)
{assert(dev==&device && !flags);if(init_fault==2)return NULL;
 void *p=calloc(1,n);assert(p);manage(p,free);return p;}
static void *devm_ioremap_resource(struct device *dev,const struct resource *res)
{assert(dev==&device && res->start==properties[1] && res->end==(uint64_t)properties[1]+properties[0]-1);
 assert(!strcmp(res->name,"mt8901-afe-sram"));if(init_fault==3)return ERR_PTR(-EBUSY);
 mapping=aligned_alloc(16,properties[0]);assert(mapping);memset(mapping,0xa5,properties[0]);
 manage(mapping,free);return mapping;}
static struct gen_pool *gen_pool_create(int order,int nid)
{assert(order==4 && nid==-1);if(init_fault==4)return NULL;
 struct gen_pool *p=calloc(1,sizeof(*p));assert(p);pools++;return p;}
static int gen_pool_add_virt(struct gen_pool *p,unsigned long virt,unsigned long phys,size_t n,int nid)
{assert(p && virt==(unsigned long)mapping && phys==properties[1] && n==properties[0] && nid==-1);
 p->base=virt;return init_fault==5?-EINVAL:0;}
static void gen_pool_destroy(struct gen_pool *p)
{assert(p && pools);for(unsigned i=0;i<5120;i++)assert(!p->used[i]);pools--;free(p);}
static int devm_add_action_or_reset(struct device *dev,void (*action)(void *),void *p)
{assert(dev==&device);if(init_fault==6){action(p);return -ENOMEM;}manage(p,action);return 0;}
static unsigned long gen_pool_alloc(struct gen_pool *p,size_t n)
{
 assert(locked && pm_refs && pm_active && n && !(n%16));
 for(unsigned start=0;start+n/16<=5120;start++){
  bool free=true;for(unsigned i=start;i<start+n/16;i++)if(p->used[i]){free=false;break;}
  if(free){memset(p->used+start,1,n/16);return p->base+16*start;}
 }return 0;
}
static void gen_pool_free(struct gen_pool *p,unsigned long address,size_t n)
{assert(locked && pm_refs && address>=p->base && n && !(n%16));unsigned start=(address-p->base)/16;
 assert(start+n/16<=5120);for(unsigned i=start;i<start+n/16;i++)assert(p->used[i]);memset(p->used+start,0,n/16);}
static bool try_module_get(void *module)
{assert(module==THIS_MODULE && locked);if(!module_alive)return false;module_refs++;return true;}
static void module_put(void *module) {assert(module==THIS_MODULE && module_refs);module_refs--;}
static struct device *get_device(struct device *dev) {assert(locked);if(dev==&card_device){card_refs++;return dev;}assert(dev==&device);device_refs++;return dev;}
static void put_device(struct device *dev) {if(dev==&card_device){assert(card_refs);card_refs--;return;}assert(dev==&device && device_refs);device_refs--;}
static bool pm_runtime_enabled(struct device *dev) {assert(dev==&device && locked);return pm_enabled;}
static int pm_runtime_resume_and_get(struct device *dev)
{assert(dev==&device && locked && module_refs);if(resume_error)return resume_error;pm_refs++;pm_active=true;return 0;}
static void pm_runtime_put(struct device *dev) {assert(dev==&device && locked && pm_refs);pm_refs--;}
static int pm_runtime_put_sync(struct device *dev)
{assert(dev==&device && locked && pm_refs);pm_refs--;if(pm_refs)return 1;
 int ret=mt8901_afe_runtime_suspend(dev);if(!ret)pm_active=false;return ret;}
static void *lease_alloc(size_t n)
{if(allocation_fails)return NULL;void *p=calloc(1,n);assert(p);allocations++;return p;}
#define kzalloc_obj(obj) lease_alloc(sizeof(obj))
static void kfree(void *p) {assert(p && allocations);allocations--;free(p);}
static void memcpy_fromio(void *to,const void *from,size_t n) {assert(n==properties[0]);memcpy(to,from,n);}
static void memcpy_toio(void *to,const void *from,size_t n) {assert(n==properties[0]);memcpy(to,from,n);}
static void memset_io(void *p,int value,size_t n)
{assert(locked && pm_refs && pm_active && (unsigned char *)p>=mapping && (unsigned char *)p+n<=mapping+81920);
 io_bytes+=n;memset(p,value,n);}
static void wmb(void) {assert(locked && pm_refs && pm_active);barriers++;}
#define WARN_ON(condition) ((condition)?(assert(!(condition)),1):0)
static int mt8901_afe_datapath_off(struct mtk_base_afe *a) {assert(a==&afe);hardware_calls++;return datapath_error;}
static void mt8901_afe_datapath_on(struct mtk_base_afe *a) {assert(a==&afe);hardware_calls++;}
static int mt8901_afe_disable_reg_rw_clk(struct mtk_base_afe *a) {assert(a==&afe);hardware_calls++;return 0;}
static void mt8901_afe_enable_reg_rw_clk(struct mtk_base_afe *a) {assert(a==&afe);hardware_calls++;}
static int mt8901_afe_disable_mtcmos(struct mtk_base_afe *a,int pd) {assert(a==&afe && pd==AUDIO_PD);hardware_calls++;return 0;}
static void regcache_cache_only(void *map,bool only) {assert(map==(void *)3);(void)only;hardware_calls++;}
static void regcache_mark_dirty(void *map) {assert(map==(void *)3);hardware_calls++;}
#define dev_warn(dev,...) ((void)(dev))
static bool dsp_enabled;
static bool mt8901_afe_dsp_enabled(void){return dsp_enabled;}
#define MT8901_AFE_MEMIF_DL0 0
#define MT8901_AFE_MEMIF_DL1 1
#define MT8901_AFE_MEMIF_UL1 8
static unsigned long mt8901_get_prefetch_delay(struct mtk_base_afe *a,int id,unsigned minlen,unsigned rate,unsigned channels,unsigned bits)
{(void)a;(void)id;(void)minlen;(void)rate;(void)channels;(void)bits;return 1;}
static void udelay(unsigned long us) {assert(us==1);}
''' + domain + owner + suspend + r'''
static void reset(void)
{
 assert(!locked && !allocations && !module_refs && !device_refs && !pm_refs && !node_refs);
 cleanup();assert(!pools);memset(&private,0,sizeof(private));
 device.driver=&mt8901_afe_pcm_driver.driver;device.data=&afe;
 afe.dev=&device;afe.platform_priv=&private;afe.regmap=(void *)3;
 afe.memif_size=16;afe.irqs_size=22;
 dai=(struct snd_soc_dai){.dev=&device,.id=0,.data=&afe};rtd.cpu=&dai;
 card=(struct snd_soc_card){.dev=&card_device,.snd_card=&pcm,.instantiated=true};
 pcm.card=&pcm;rtd.card=&card;
 runtime=(struct snd_pcm_runtime){.rate=48000,.channels=2,.sample_bits=16,.period_size=480,.periods=2};
 stream=(struct snd_pcm_substream){.pcm=&pcm,.runtime=&runtime,.rtd=&rtd};
 for(unsigned i=0;i<16;i++){afe.memif[i].substream=&stream;afe.memif[i].irq_usage=i;}
 for(unsigned i=0;i<22;i++)afe.irqs[i].irq_occupyed=true;
 init_fault=property_fault=property_changed=resume_error=datapath_error=0;dsp_enabled=false;
 property_present=node_present=module_alive=pm_enabled=true;pm_active=allocation_fails=false;
 version=count=1;memcpy(properties,(u32[]){81920,0x1a6c0000,0x1a6c0000,0x4e5c0000},sizeof(properties));
 io_bytes=barriers=hardware_calls=0;mapping=NULL;
 program_calls=program_fail_at=expected_offset=expected_irq=0;
 memif_data=(struct mtk_base_memif_data){.reg_ofs_base=0x10,.reg_ofs_end=0x14,.reg_ofs_base_msb=0x18,.reg_ofs_end_msb=0x1c,.enable_reg=AFE_DL0_CON0,.enable_shift=28};
 for(unsigned i=0;i<16;i++){afe.memif[i].data=&memif_data;afe.memif[i].dma_area=(void *)0x1234;afe.memif[i].dma_addr=0xe0000000;afe.memif[i].dma_bytes=3840;}
 afe.get_memif_pbuf_size=NULL;afe.irq_fs=irq_fs;
 irq_data=(struct mtk_base_irq_data){.irq_cnt_reg=0x9d44,.irq_cnt_maskbit=0xffffff,
 .irq_fs_reg=0x9d40,.irq_fs_shift=4,.irq_fs_maskbit=0x1f,.irq_domain_reg=0x9d40,
 .irq_domain_shift=9,.irq_domain_maskbit=7,.irq_en_reg=0x9d40,
 .irq_clr_reg=0x9d44,.irq_clr_shift=31,.irq_mask_reg=0x9d00};
 for(unsigned i=0;i<22;i++)afe.irqs[i].irq_data=&irq_data;
 memif_clock=(struct mtk_dai_memif_priv){.domain=1};private.dai_priv[0]=&memif_clock;
 irq_updates=irq_fail_at=stop_calls=stop_fail_step=0;irq_stopping=false;
 engine_starting=false;engine_updates=engine_fail_at=0;memif_word=0x01234567;
 mcu_word=0xa5a50001;dsp_word=0x5a5a0001;clear_read=0;irq_read_error=0;fs_value=10;cfg_word=0xa5a50000;counter_word=0x10000000;
}
static void init(void) {assert(!mt8901_afe_sram_init(&afe) && private.sram && !node_refs && !io_bytes);}
static void empty(void) {assert(!allocations && !module_refs && !device_refs && !pm_refs && !mt8901_afe_sram_busy(&afe));}
static int force_suspend(void) {device_lock(&device);int ret=mt8901_afe_runtime_suspend(&device);device_unlock(&device);return ret;}
static pthread_barrier_t rendezvous;
static struct mt8901_afe_sram_view concurrent_views[8];
static void *reserve_thread(void *arg)
{
 unsigned id=(uintptr_t)arg;struct mt8901_afe_sram_buffer *b=mt8901_afe_sram_reserve(&device,3840);
 assert(!IS_ERR(b) && !mt8901_afe_sram_view(b,&concurrent_views[id]));
 int ret=pthread_barrier_wait(&rendezvous);assert(!ret || ret==PTHREAD_BARRIER_SERIAL_THREAD);
 assert(!mt8901_afe_sram_release(b));return NULL;
}
static void *prepare_thread(void *arg)
{assert(!mt8901_afe_sram_prepare(arg));return NULL;}
static void *irq_prepare_thread(void *arg)
{assert(!mt8901_afe_sram_prepare_irq(arg));return NULL;}
int main(void)
{
 reset();assert(IS_ERR(mt8901_afe_pcm_card_device(NULL)));
 for(unsigned fault=0;fault<10;fault++) {
  reset();
  switch(fault){case 1:card.instantiated=false;break;case 2:card.dev=NULL;break;
   case 3:pcm.card=NULL;break;case 4:stream.pcm=NULL;break;case 5:stream.stream=1;break;
   case 6:afe.memif[0].substream=NULL;break;case 7:device.driver=NULL;break;
   case 8:dai.id=2;break;case 9:rtd.card=NULL;break;}
  struct device *result=mt8901_afe_pcm_card_device(&stream);
  if(!fault){assert(result==&card_device && card_refs==1);put_device(result);}
  else assert(IS_ERR(result) && !card_refs);
 }
 reset();property_present=false;assert(!mt8901_afe_sram_init(&afe) && !private.sram && !managed_count);
 for(unsigned fault=0;fault<12;fault++){
  reset();if(fault==0)version=2;else if(fault==1)count=2;else if(fault==2)node_present=false;
  else if(fault<8)property_fault=fault-2;else property_changed=fault-7;
  assert(mt8901_afe_sram_init(&afe)<0 && !private.sram && !node_refs && !managed_count && !pools && !io_bytes);
 }
 /* A different firmware SRAM tuple is accepted without any host identity. */
 reset();properties[0]=4096;properties[1]=0x20000000;properties[2]=0x30000000;properties[3]=0x50000000;
 init();struct mt8901_afe_sram_buffer *relocated=mt8901_afe_sram_reserve(&device,4096);
 struct mt8901_afe_sram_view relocated_view;assert(!IS_ERR(relocated));
 assert(!mt8901_afe_sram_view(relocated,&relocated_view));
 assert(relocated_view.bytes==4096 && relocated_view.cpu_address==properties[1] &&
        relocated_view.afe_address==properties[2] && relocated_view.dsp_address==properties[3]);
 assert(!mt8901_afe_sram_release(relocated));empty();
 for(unsigned field=0;field<4;field++){
  reset();properties[field]=0;assert(mt8901_afe_sram_init(&afe)<0 && !managed_count);
 }
 for(unsigned field=1;field<4;field++){
  reset();properties[field]=0xfffffff0U;assert(mt8901_afe_sram_init(&afe)==-ERANGE && !managed_count);
 }
 for(unsigned fault=1;fault<=6;fault++){
  reset();init_fault=fault;assert(mt8901_afe_sram_init(&afe)<0);
  assert(!private.sram && !node_refs && !managed_count && !pools && !io_bytes);
 }
 reset();assert(PTR_ERR(mt8901_afe_sram_reserve(&device,16))==-EOPNOTSUPP);empty();init();
 for(unsigned fault=0;fault<5;fault++){
  size_t bytes=(size_t[]){0,1,15,81921,81936}[fault];
  assert(PTR_ERR(mt8901_afe_sram_reserve(&device,bytes))==-EINVAL);empty();
 }
 assert(PTR_ERR(mt8901_afe_sram_reserve(NULL,16))==-EINVAL);
 for(unsigned fault=0;fault<5;fault++){
  const int expected[]={ENOMEM,ENODEV,ENODEV,EHOSTDOWN,EIO};
  allocation_fails=fault==0;device.driver=fault==1?NULL:&mt8901_afe_pcm_driver.driver;
  module_alive=fault!=2;pm_enabled=fault!=3;resume_error=fault==4?-EIO:0;
  assert(PTR_ERR(mt8901_afe_sram_reserve(&device,16))==-expected[fault]);empty();assert(!io_bytes);
 }
 reset();init();struct mt8901_afe_sram_buffer *b=mt8901_afe_sram_reserve(&device,81920);
 assert(!IS_ERR(b) && module_refs==1 && device_refs==1 && pm_refs==1 && allocations==1);
 assert(PTR_ERR(mt8901_afe_sram_reserve(&device,16))==-ENOMEM);
 assert(module_refs==1 && device_refs==1 && pm_refs==1 && allocations==1);
 struct mt8901_afe_sram_view view;
 assert(!mt8901_afe_sram_view(b,&view) && view.area==mapping && view.bytes==81920);
 assert(view.cpu_address==0x1a6c0000 && view.afe_address==0x1a6c0000 && view.dsp_address==0x4e5c0000);
 for(unsigned i=0;i<81920;i++)assert(!mapping[i]);memset(mapping,0xa5,81920);
 assert(force_suspend()==-EBUSY && !hardware_calls && mt8901_afe_sram_busy(&afe));
 assert(!mt8901_afe_sram_release(b));empty();
 b=mt8901_afe_sram_reserve(&device,16);assert(!IS_ERR(b));
 for(unsigned i=0;i<16;i++)assert(!mapping[i]);assert(!mt8901_afe_sram_release(b));empty();
 memset(&view,0xa5,sizeof(view));struct mt8901_afe_sram_view before=view;
 assert(mt8901_afe_sram_view(NULL,&view)==-EINVAL && !memcmp(&view,&before,sizeof(view)));
 assert(mt8901_afe_sram_view(ERR_PTR(-ENOMEM),&view)==-EINVAL);
 assert(mt8901_afe_sram_publish(NULL)==-EINVAL && mt8901_afe_sram_release(NULL)==-EINVAL);
 reset();init();b=mt8901_afe_sram_reserve(&device,16);datapath_error=-EIO;
 assert(mt8901_afe_sram_release(b)==-EIO);empty();
 reset();init();pid_t child=fork();assert(child>=0);
 if(!child){
  b=mt8901_afe_sram_reserve(&device,3840);assert(!IS_ERR(b));
  assert(!mt8901_afe_sram_bind(b,&stream));
  assert(!mt8901_afe_sram_publish(b) && barriers==1);
  assert(mt8901_afe_sram_release(b)==-EBUSY);
  assert(module_refs==1 && device_refs==1 && pm_refs==1 && allocations==1 && atomic_read(&private.sram->users)==1);
  assert(force_suspend()==-EBUSY && !hardware_calls);
  assert(mt8901_afe_sram_startup(&stream,&dai)==-EBUSY);
  assert(!mt8901_afe_sram_view(b,&view) && view.bytes==3840 && !mt8901_afe_sram_publish(b));
  struct mt8901_afe_sram_endpoint snapshot;
  assert(!mt8901_afe_sram_endpoint(b,&snapshot,sizeof(snapshot)) && snapshot.published);
  assert(barriers==2 && module_refs==1 && pm_refs==1);
  _exit(0); /* End the retained-buffer fixture; no production release bypass. */
 }
 int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));empty();
 b=mt8901_afe_sram_reserve(&device,3840);assert(!IS_ERR(b));
 assert(PTR_ERR(mt8901_afe_sram_reserve_ipc(NULL,2048))==-EINVAL);
 assert(PTR_ERR(mt8901_afe_sram_reserve_ipc(ERR_PTR(-ENOMEM),2048))==-EINVAL);
 assert(mt8901_afe_sram_publish_ipc(NULL)==-EINVAL);
 assert(PTR_ERR(mt8901_afe_sram_reserve_ipc(b,2048))==-EINVAL);
 assert(!mt8901_afe_sram_bind(b,&stream));
 for(unsigned i=0;i<5;i++){
  size_t bytes=(size_t[]){0,16,1023,4097,5120}[i];
  assert(PTR_ERR(mt8901_afe_sram_reserve_ipc(b,bytes))==-EINVAL);
 }
 assert(mt8901_afe_sram_publish_ipc(b)==-EINVAL && !barriers);
 for(size_t bytes=1024;bytes<=4096;bytes+=1024){
  struct mt8901_afe_sram_buffer *ipc=mt8901_afe_sram_reserve_ipc(b,bytes);assert(!IS_ERR(ipc));
  assert(ipc->ipc && !ipc->substream && module_refs==2 && pm_refs==2);
  assert(!mt8901_afe_sram_view(ipc,&view) && view.bytes==bytes);
  assert(view.cpu_address>=0x1a6c0000+3840 && view.cpu_address+bytes<=0x1a6d4000);
  assert(mt8901_afe_sram_bind(ipc,&stream)==-EINVAL && mt8901_afe_sram_publish(ipc)==-ENODEV);
  assert(PTR_ERR(mt8901_afe_sram_reserve_ipc(ipc,1024))==-EINVAL);
  assert(!mt8901_afe_sram_release(ipc) && module_refs==1 && pm_refs==1);
 }
 allocation_fails=true;assert(PTR_ERR(mt8901_afe_sram_reserve_ipc(b,2048))==-ENOMEM);
 allocation_fails=false;assert(module_refs==1 && pm_refs==1);
 child=fork();assert(child>=0);
 if(!child){
  struct mt8901_afe_sram_buffer *ipc=mt8901_afe_sram_reserve_ipc(b,2048);assert(!IS_ERR(ipc));
  assert(!mt8901_afe_sram_publish_ipc(ipc) && barriers==1);
  assert(mt8901_afe_sram_release(ipc)==-EBUSY && !mt8901_afe_sram_release(b));
  assert(module_refs==1 && device_refs==1 && pm_refs==1 && force_suspend()==-EBUSY);
  _exit(0);
 }
 assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
 assert(!mt8901_afe_sram_release(b));empty();
 for(unsigned fault=0;fault<20;fault++){
  reset();init();b=mt8901_afe_sram_reserve(&device,3840);assert(!IS_ERR(b));
  struct mt8901_afe_sram_endpoint endpoint,before;memset(&before,0xa5,sizeof(before));endpoint=before;
  switch(fault){
  case 0:stream.stream=1;break;case 1:stream.runtime=NULL;break;case 2:runtime.running=true;break;
  case 3:runtime.rate=0;break;case 4:runtime.channels=3;break;case 5:runtime.sample_bits=24;break;
  case 6:runtime.period_size=0;break;case 7:runtime.period_size=0x80000000ULL;break;
  case 8:runtime.periods=1;break;case 9:runtime.periods=0x80000000U;break;
  case 10:runtime.period_size=479;break;case 11:dai.id=-1;break;case 12:dai.id=7;break;
  case 13:dai.dev=NULL;break;case 14:dai.data=NULL;break;case 15:afe.memif[0].substream=NULL;break;
  case 16:afe.memif[0].irq_usage=-1;break;case 17:afe.irqs[0].irq_occupyed=false;break;
  case 18:afe.memif_size=0;break;case 19:afe.irqs_size=0;break;}
  assert(mt8901_afe_sram_bind(b,&stream)<0 && !b->substream);
  assert(mt8901_afe_sram_endpoint(b,&endpoint,sizeof(endpoint))==-ENODEV && !memcmp(&endpoint,&before,sizeof(endpoint)));
  assert(mt8901_afe_sram_publish(b)==-ENODEV && !barriers);
  assert(!mt8901_afe_sram_release(b));empty();
 }

 reset();init();child=fork();assert(child>=0);
 if(!child){
  struct mt8901_afe_sram_buffer *ring=mt8901_afe_sram_reserve(&device,3840);
  assert(!IS_ERR(ring) && !mt8901_afe_sram_bind(ring,&stream));
  struct mt8901_afe_sram_buffer *ipc=mt8901_afe_sram_reserve_ipc(ring,2048);assert(!IS_ERR(ipc));
  assert(!mt8901_afe_sram_publish(ring) && !mt8901_afe_sram_publish_ipc(ipc));
  device_lock(&device);assert(mt8901_afe_sram_pm_prepare(&afe)==-EBUSY);device_unlock(&device);
  assert(!mt8901_afe_sram_allow_retention(ring) && !mt8901_afe_sram_allow_retention(ipc));
  assert(!mt8901_afe_sram_allow_retention(ring) && atomic_read(&private.sram->retention_users)==2);
  for(unsigned cycle=0;cycle<16;cycle++){
   device_lock(&device);assert(!mt8901_afe_sram_pm_prepare(&afe));device_unlock(&device);
   assert(PTR_ERR(mt8901_afe_sram_reserve(&device,16))==-EBUSY);
   runtime.running=true;assert(mt8901_afe_sram_suspend(ring)==-EBUSY);runtime.running=false;
   assert(!mt8901_afe_sram_suspend(ring) && mt8901_afe_sram_suspend(ring)==-EALREADY);
   device_lock(&device);assert(mt8901_afe_sram_pm_save(&afe)==-EBUSY);device_unlock(&device);
   assert(!mt8901_afe_sram_suspend(ipc));
   device_lock(&device);assert(!mt8901_afe_sram_pm_save(&afe) && !mt8901_afe_sram_busy(&afe));device_unlock(&device);
   assert(mt8901_afe_sram_resume(ring)==-EHOSTDOWN);
   memset(mapping,0xcc,private.sram->bytes); /* Simulate loss of powered SRAM. */
   device_lock(&device);mt8901_afe_sram_pm_restore(&afe);device_unlock(&device);
   assert(!memcmp(mapping,private.sram->snapshot,private.sram->bytes));
   assert(!mt8901_afe_sram_resume(ring) && !mt8901_afe_sram_resume(ipc));
   device_lock(&device);mt8901_afe_sram_pm_complete(&afe);device_unlock(&device);
   assert(atomic_read(&private.sram->users)==2 && !atomic_read(&private.sram->sleeping_users));
   assert(module_refs==2 && pm_refs==2 && ring->published && ipc->published);
  }
  assert(mt8901_afe_sram_rebind(ring,&stream)==-EBUSY);
  mt8901_afe_sram_retire(ring);
  struct snd_pcm_runtime next_runtime=runtime;next_runtime.period_size=240;
  struct snd_pcm_substream next_stream=stream;next_stream.runtime=&next_runtime;
  afe.memif[0].substream=&next_stream;
  assert(mt8901_afe_sram_startup(&next_stream,&dai)==-EBUSY);
  dsp_enabled=true;assert(!mt8901_afe_sram_startup(&next_stream,&dai));
  assert(!mt8901_afe_sram_rebind(ring,&next_stream));
  struct mt8901_afe_sram_endpoint endpoint;
  assert(!mt8901_afe_sram_endpoint(ring,&endpoint,sizeof(endpoint)));
  assert(endpoint.memory.bytes==1920 && ring->bytes==3840 && ring->published);
  assert(mt8901_afe_sram_release(ring)==-EBUSY && mt8901_afe_sram_release(ipc)==-EBUSY);
  _exit(0);
 }
 assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
 for(unsigned fault=0;fault<9;fault++) {
  reset();init();child=fork();assert(child>=0);
  if(!child) {
   b=mt8901_afe_sram_reserve(&device,3840);assert(!IS_ERR(b));
   assert(!mt8901_afe_sram_bind(b,&stream) && !mt8901_afe_sram_publish(b));
   mt8901_afe_sram_retire(b);afe.memif[0].substream=NULL;
   struct mtk_base_memif_data next=memif_data;next.enable_reg=AFE_DL1_CON0;
   afe.memif[1].data=&next;dai.id=1;afe.memif[1].substream=&stream;
   moving=true;move_reads=move_fail=0;memset(move_words,0,sizeof(move_words));
   if(fault>=1 && fault<=4)move_words[fault-1]=(fault==1 || fault==3)?1:BIT(28);
   if(fault>=5)move_fail=fault-4;
   int result=mt8901_afe_sram_rebind(b,&stream);
   if(!fault) {
    assert(!result && move_reads==4 && !private.sram->memif[0] && private.sram->memif[1]==b);
    assert(b->endpoint.memif==1 && b->endpoint.irq==1 && b->substream==&stream);
   } else {
    assert(result==(fault>=5?-EIO:-EBUSY));
    assert(private.sram->memif[0]==b && !private.sram->memif[1] && !b->substream && !b->endpoint.memif);
   }
   assert(b->published && module_refs==1 && pm_refs==1);
   _exit(0);
  }
  assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
 }
 assert(mt8901_afe_sram_prepare(NULL)==-EINVAL && mt8901_afe_sram_prepare(ERR_PTR(-EIO))==-EINVAL);
 for(unsigned fault=0;fault<28;fault++){
  reset();init();child=fork();assert(child>=0);
  if(!child){
   struct mt8901_afe_sram_buffer *spacer=mt8901_afe_sram_reserve(&device,16);
   assert(!IS_ERR(spacer));b=mt8901_afe_sram_reserve(&device,3840);assert(!IS_ERR(b));
   assert(!mt8901_afe_sram_bind(b,&stream) && !mt8901_afe_sram_publish(b));expected_offset=16;
   switch(fault){
   case 0:b->substream=NULL;break;case 1:b->published=false;break;case 2:b->ipc=true;break;
   case 3:device.driver=NULL;break;case 4:runtime.rate=44100;break;case 5:runtime.running=true;break;
   case 6:afe.memif[0].substream=NULL;break;case 7:dai.dev=NULL;break;case 8:dai.id=1;break;
   case 9:dai.data=NULL;break;case 10:afe.memif[0].irq_usage=1;break;
   case 11:afe.irqs[0].irq_occupyed=false;break;case 12:private.sram->memif[0]=NULL;break;
   case 13:case 14:case 15:case 16:program_fail_at=fault-12;break;
   case 18:afe.memif[0].data=NULL;break;case 19:memif_data.reg_ofs_base=0;break;
   case 20:memif_data.reg_ofs_end++;break;case 21:memif_data.reg_ofs_base_msb=0;break;
   case 22:memif_data.reg_ofs_end_msb=-1;break;case 23:memif_data.msb_reg=4;break;
   case 24:memif_data.msb_end_reg=4;break;case 25:afe.get_memif_pbuf_size=unsupported_pbuf;break;
   case 26:b->endpoint.memory.afe_address=1ULL<<32;break;
   case 27:b->endpoint.memory.afe_address=U32_MAX-16;break;

   }
   struct snd_pcm_runtime before_runtime=runtime;
   if(fault==17){
    pthread_t workers[8];
    for(unsigned i=0;i<8;i++)assert(!pthread_create(&workers[i],NULL,prepare_thread,b));
    for(unsigned i=0;i<8;i++)assert(!pthread_join(workers[i],NULL));
    assert(b->prepared && !b->prepare_error && program_calls==4 && !irq_updates);
    assert(!mt8901_afe_sram_prepare(b) && program_calls==4);
    struct mt8901_afe_sram_endpoint prepared;assert(!mt8901_afe_sram_endpoint(b,&prepared,sizeof(prepared)) && !prepared.irq_prepared && prepared.abi_version==2);
    dai.id=1;assert(mt8901_afe_sram_prepare(b)==-EBUSY);dai.id=0;
    runtime.running=true;assert(mt8901_afe_sram_prepare(b)==-EBUSY);runtime.running=false;
   }else if(fault>=13 && fault<=16){
    int error=-EIO;unsigned failed_at=program_fail_at;
    assert(mt8901_afe_sram_prepare(b)==error && !b->prepared && b->prepare_error==error);
    assert(program_calls==failed_at);program_fail_at=0;
    assert(mt8901_afe_sram_prepare(b)==error && program_calls==failed_at);
   }else{
    assert(mt8901_afe_sram_prepare(b)<0 && !program_calls && !b->prepare_error && !b->prepared);
   }
   if(fault==17){
    assert(afe.memif[0].dma_area==mapping+16 && afe.memif[0].dma_addr==0x1a6c0010 && afe.memif[0].dma_bytes==3840);
   }else{
    assert(afe.memif[0].dma_area==(void *)0x1234 && afe.memif[0].dma_addr==0xe0000000 && afe.memif[0].dma_bytes==3840);
   }
   assert(!memcmp(&runtime,&before_runtime,sizeof(runtime)));
   if(b->published)assert(mt8901_afe_sram_release(b)==-EBUSY);
   assert(module_refs==2 && device_refs==2 && pm_refs==2 && allocations==2);
   for(unsigned i=0;i<3856;i++)assert(!mapping[i]);
   _exit(0);
  }
  assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));empty();
 }
 assert(mt8901_afe_sram_prepare_irq(NULL)==-EINVAL && mt8901_afe_sram_prepare_irq(ERR_PTR(-EIO))==-EINVAL);
 for(unsigned fault=0;fault<31;fault++){
  reset();init();child=fork();assert(child>=0);
  if(!child){
   struct mt8901_afe_sram_buffer *spacer=mt8901_afe_sram_reserve(&device,16);assert(!IS_ERR(spacer));
   b=mt8901_afe_sram_reserve(&device,3840);assert(!IS_ERR(b));expected_offset=16;
   assert(!mt8901_afe_sram_bind(b,&stream) && !mt8901_afe_sram_publish(b));
   if(fault==24){program_fail_at=1;assert(mt8901_afe_sram_prepare(b)==-EIO);program_fail_at=0;}
   else if(fault!=23)assert(!mt8901_afe_sram_prepare(b));
   assert(!irq_updates && !b->irq_prepared);
   switch(fault){
   case 0:afe.irqs[0].irq_data=NULL;break;case 1:afe.irq_fs=NULL;break;
   case 2:irq_data.id=1;break;case 3:irq_data.irq_fs_reg++;break;case 4:irq_data.irq_fs_shift=32;break;
   case 5:irq_data.irq_fs_maskbit=0;break;case 6:irq_data.irq_domain_reg++;break;
   case 7:irq_data.irq_domain_shift=32;break;case 8:irq_data.irq_domain_maskbit=3;break;
   case 9:irq_data.irq_cnt_reg++;break;case 10:irq_data.irq_cnt_shift=1;break;case 11:irq_data.irq_cnt_maskbit=0x7fffffff;break;
   case 12:irq_data.irq_en_reg++;break;case 13:irq_data.irq_en_shift=31;break;
   case 14:fs_value=-EIO;break;case 15:fs_value=32;break;case 16:private.dai_priv[0]=NULL;break;
   case 17:memif_clock.domain=8;break;case 18:b->endpoint.period_frames=runtime.period_size=0x1000000;break;
   case 19:irq_read_error=-EIO;break;case 20:cfg_word|=1;break;
   case 21:irq_fail_at=1;break;case 25:irq_fail_at=2;break;case 26:irq_fail_at=3;break;
   case 27:runtime.running=true;break;case 28:runtime.rate=44100;break;
   case 29:dai.dev=NULL;break;case 30:afe.irqs[0].irq_occupyed=false;break;
   }
   unsigned address_writes=program_calls;struct snd_pcm_runtime before_runtime=runtime;
   if(fault==22){
    pthread_t workers[8];
    for(unsigned i=0;i<8;i++)assert(!pthread_create(&workers[i],NULL,irq_prepare_thread,b));
    for(unsigned i=0;i<8;i++)assert(!pthread_join(workers[i],NULL));
    assert(b->irq_prepared && !b->irq_error && irq_updates==3);
    assert(cfg_word==(0xa5a50000|(10<<4)|(1<<9)) && counter_word==(0x10000000|480));
    assert(!mt8901_afe_sram_prepare_irq(b) && irq_updates==3);
    struct mt8901_afe_sram_endpoint ready;
    assert(!mt8901_afe_sram_endpoint(b,&ready,sizeof(ready)) && ready.irq_prepared);
   }else if(fault==21 || fault==25 || fault==26){
    unsigned failed_at=irq_fail_at;
    assert(mt8901_afe_sram_prepare_irq(b)==-EIO && !b->irq_prepared && b->irq_error==-EIO);
    assert(irq_updates==failed_at);irq_fail_at=0;
    assert(mt8901_afe_sram_prepare_irq(b)==-EIO && irq_updates==failed_at);
   }else{
    assert(mt8901_afe_sram_prepare_irq(b)<0 && !irq_updates && !b->irq_error && !b->irq_prepared);
   }
   assert(program_calls==address_writes && !memcmp(&runtime,&before_runtime,sizeof(runtime)));
   assert(mt8901_afe_sram_release(b)==-EBUSY && module_refs==2 && device_refs==2 && pm_refs==2);
   for(unsigned i=0;i<3856;i++)assert(!mapping[i]);
   _exit(0);
  }
  assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));empty();
 }
 reset();init();child=fork();assert(child>=0);
 if(!child) {
  engine_memif=expected_irq=dai.id=8;stream.stream=1;memif_data.enable_reg=AFE_VUL1_CON0;
  irq_data.id=irq_data.irq_mask_shift=8;irq_data.irq_en_reg=0x9d80;
  irq_data.irq_cnt_reg=irq_data.irq_clr_reg=0x9d84;
  irq_data.irq_fs_reg=irq_data.irq_domain_reg=0x9d80;private.dai_priv[8]=&memif_clock;
  b=mt8901_afe_sram_reserve(&device,3840);assert(!IS_ERR(b));
  assert(!mt8901_afe_sram_bind(b,&stream) && !mt8901_afe_sram_publish(b));
  assert(!mt8901_afe_sram_prepare(b));
  for(unsigned cycle=0;cycle<32;cycle++) {
   irq_updates=0;assert(!mt8901_afe_sram_prepare_irq(b));
   runtime.running=true;engine_starting=true;engine_updates=0;
   assert(!mt8901_afe_sram_start_pcm(&stream,&dai) && engine_updates==7 && b->started);
   assert(dsp_word&BIT(8));assert(!(mcu_word&BIT(8)) && (memif_word&BIT(28)) && (cfg_word&1));
   engine_starting=false;irq_stopping=true;stop_calls=0;
   assert(mt8901_afe_sram_stop_irq(b,2)==-EOPNOTSUPP && !stop_calls);
   assert(!mt8901_afe_sram_stop_irq(b,3) && stop_calls==6 && !b->started);
   assert(!(dsp_word&BIT(8)) && !(memif_word&BIT(28)) && !(cfg_word&1));
   runtime.running=false;irq_stopping=false;
  }
  _exit(0);
 }
 assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
 assert(mt8901_afe_sram_start_pcm(NULL,&dai)==-EINVAL);
 assert(mt8901_afe_sram_start_pcm(&stream,NULL)==-EINVAL);
 for(unsigned fault=0;fault<30;fault++) {
  reset();init();child=fork();assert(child>=0);
  if(!child) {
   b=mt8901_afe_sram_reserve(&device,3840);assert(!IS_ERR(b));
   assert(!mt8901_afe_sram_bind(b,&stream) && !mt8901_afe_sram_publish(b));
   assert(!mt8901_afe_sram_prepare(b) && !mt8901_afe_sram_prepare_irq(b));
   runtime.running=true;engine_starting=true;dsp_word&=~BIT(0);
   u32 old_memif=memif_word,old_cfg=cfg_word,old_mcu=mcu_word,old_dsp=dsp_word;
   switch(fault) {
   case 1:case 2:case 3:case 4:case 5:case 6:case 7:engine_fail_at=fault;break;
   case 8:b->irq_prepared=false;break;case 9:b->substream=NULL;break;
   case 10:b->published=false;break;case 11:b->sram->sleep_prepared=true;break;
   case 12:b->sram->sleep_saved=true;break;case 13:memif_data.enable_reg+=4;break;
   case 14:memif_data.enable_shift=27;break;case 15:irq_data.irq_en_reg+=4;break;
   case 16:device.driver=NULL;break;case 17:dai.id=1;break;
   case 18:b->start_error=-EIO;break;case 19:runtime.rate++;break;
   case 20:b->sram->memif[0]=NULL;break;case 21:b->prepared=false;break;
   case 22:b->ipc=true;break;case 23:private.sram=NULL;break;
   case 24:stream.stream=1;break;case 25:b->irq_stopped=true;break;
   case 26:b->irq_stop_error=-EIO;break;case 27:irq_data.irq_mask_reg+=4;break;
   case 28:irq_data.irq_en_shift=1;break;
   case 29:dai.dev=NULL;break;
   }
   if(!fault){cfg_word&=~((0x1fU<<4)|(7U<<9));counter_word&=~0xffffffU;}
   int result=mt8901_afe_sram_start_pcm(&stream,&dai);
   if(!fault) {
    assert(!result && b->started && engine_updates==7);
    assert(memif_word==(old_memif|BIT(28)) && cfg_word==(old_cfg|1U));
    assert(mcu_word==(old_mcu&~1U) && dsp_word==(old_dsp|1U));
    assert(!mt8901_afe_sram_start_pcm(&stream,&dai) && engine_updates==7);
    for(unsigned cycle=0;cycle<32;cycle++) {
     engine_starting=false;irq_stopping=true;stop_calls=0;
     assert(!mt8901_afe_sram_stop_irq(b,2) && stop_calls==6 && !b->started);
     assert(memif_word==old_memif && cfg_word==old_cfg && !(dsp_word&1U));
     runtime.running=false;irq_stopping=false;irq_updates=0;
     assert(!mt8901_afe_sram_prepare_irq(b));
     runtime.running=true;engine_starting=true;engine_updates=0;
     assert(!mt8901_afe_sram_start_pcm(&stream,&dai) && engine_updates==7 && b->started);
    }
   } else if(fault<=7) {
    assert(result==-EIO && engine_updates==fault && !b->started && (fault<=3?b->irq_error:b->start_error)==-EIO);
    engine_fail_at=0;assert(mt8901_afe_sram_start_pcm(&stream,&dai)==-EIO && engine_updates==fault);
    assert(mt8901_afe_sram_pm_prepare(&afe)==-ENOTRECOVERABLE);
    engine_starting=false;irq_stopping=true;
    if(fault<=3)assert(mt8901_afe_sram_stop_irq(b,2)==-EIO && !stop_calls && b->irq_error==-EIO);
    else assert(!mt8901_afe_sram_stop_irq(b,2) && stop_calls==6 && b->start_error==-EIO);
   } else {
    assert(result<0 && !engine_updates && !b->started);
    assert(memif_word==old_memif && cfg_word==old_cfg && mcu_word==old_mcu && dsp_word==old_dsp);
   }
   _exit(0);
  }
  assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));empty();
 }
 assert(mt8901_afe_sram_stop_irq(NULL,3)==-EINVAL);
 for(unsigned fault=0;fault<27;fault++){
  reset();init();child=fork();assert(child>=0);
  if(!child){
   struct mt8901_afe_sram_buffer *spacer=mt8901_afe_sram_reserve(&device,16);assert(!IS_ERR(spacer));
   b=mt8901_afe_sram_reserve(&device,3840);assert(!IS_ERR(b));expected_offset=16;
   if(fault>=20 && fault<26){
    expected_irq=fault-19;dai.id=expected_irq;private.dai_priv[expected_irq]=&memif_clock;
    irq_data.id=expected_irq;irq_data.irq_mask_shift=expected_irq;
    irq_data.irq_fs_reg=irq_data.irq_domain_reg=irq_data.irq_en_reg=0x9d40+expected_irq*8;
    irq_data.irq_cnt_reg=irq_data.irq_clr_reg=0x9d44+expected_irq*8;
    mcu_word|=BIT(expected_irq);dsp_word|=BIT(expected_irq);
   }
   assert(!mt8901_afe_sram_bind(b,&stream) && !mt8901_afe_sram_publish(b));
   assert(!mt8901_afe_sram_prepare(b) && !mt8901_afe_sram_prepare_irq(b));
   runtime.running=true;cfg_word|=1;irq_stopping=true;unsigned core=2;
   switch(fault){
   case 1:counter_word|=BIT(31);break;case 2:core=3;break;case 3:b->irq_prepared=false;break;
   case 4:b->substream=NULL;break;case 5:runtime.rate=44100;break;case 6:dai.dev=NULL;break;
   case 7:afe.memif[0].irq_usage=1;break;case 8:irq_data.id=1;break;case 9:irq_data.irq_en_reg++;break;
   case 10:irq_data.irq_en_shift=1;break;case 11:irq_data.irq_clr_reg++;break;case 12:irq_data.irq_clr_shift=30;break;
   case 13:irq_data.irq_mask_reg++;break;case 14:irq_data.irq_mask_shift=1;break;
   case 26:stop_fail_step=6;break;
   default:if(fault>=15 && fault<20)stop_fail_step=fault-14;break;
   }
   u32 before_cfg=cfg_word,before_counter=counter_word,before_mcu=mcu_word,before_dsp=dsp_word;
   if(fault<2){
    assert(!mt8901_afe_sram_stop_irq(b,core) && stop_calls==6 && b->irq_stopped && !b->irq_prepared);
    assert(cfg_word==(before_cfg&~1U) && counter_word==(before_counter^BIT(31)));
    assert(mcu_word==(before_mcu&~BIT(expected_irq)) && dsp_word==(before_dsp&~BIT(expected_irq)));
    assert(!mt8901_afe_sram_stop_irq(b,core) && stop_calls==6 && runtime.running);
    runtime.running=false;irq_stopping=false;irq_updates=0;
    assert(!mt8901_afe_sram_prepare_irq(b) && !b->irq_stopped && b->irq_prepared);
    struct mt8901_afe_sram_endpoint stopped;
    assert(!mt8901_afe_sram_endpoint(b,&stopped,sizeof(stopped)) && stopped.irq_prepared);
   }else if((fault>=15 && fault<20) || fault==26){
    unsigned failed=stop_fail_step;
    assert(mt8901_afe_sram_stop_irq(b,core)==-EIO && stop_calls==failed && !b->irq_prepared && !b->irq_stopped);
    assert(b->irq_stop_error==-EIO);stop_fail_step=0;
    assert(mt8901_afe_sram_stop_irq(b,core)==-EIO && stop_calls==failed);
    runtime.running=false;assert(mt8901_afe_sram_prepare_irq(b)==-EIO && irq_updates==3);
   }else{
    assert(mt8901_afe_sram_stop_irq(b,core)<0 && !stop_calls && !b->irq_stop_error && !b->irq_stopped);
    assert(cfg_word==before_cfg && counter_word==before_counter && mcu_word==before_mcu && dsp_word==before_dsp);
   }
   assert(program_calls==4 && irq_updates==3 && mt8901_afe_sram_release(b)==-EBUSY);
   assert(module_refs==2 && device_refs==2 && pm_refs==2);
   for(unsigned i=0;i<3856;i++)assert(!mapping[i]);
   _exit(0);
  }
  assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));empty();
 }

 reset();init();child=fork();assert(child>=0);
 if(!child){
  b=mt8901_afe_sram_reserve(&device,3840);assert(!IS_ERR(b));
  struct snd_pcm_substream *borrowed=malloc(sizeof(*borrowed));assert(borrowed);*borrowed=stream;
  afe.memif[0].substream=borrowed;assert(!mt8901_afe_sram_bind(b,borrowed));
  mt8901_afe_sram_retire(b);assert(b->substream==borrowed && !b->published);
  assert(!mt8901_afe_sram_publish(b));
  unsigned writes=program_calls+irq_updates+stop_calls;
  mt8901_afe_sram_retire(b);assert(!b->substream && b->sram->memif[0]==b);
  free(borrowed);afe.memif[0].substream=NULL;
  struct mt8901_afe_sram_endpoint retired={0},saved_retired=retired;
  assert(mt8901_afe_sram_endpoint(b,&retired,sizeof(retired))==-ENODEV);
  assert(!memcmp(&retired,&saved_retired,sizeof(retired)));
  assert(mt8901_afe_sram_prepare(b)==-ENODEV && mt8901_afe_sram_prepare_irq(b)==-ENODEV);
  assert(mt8901_afe_sram_stop_irq(b,2)==-ENODEV && mt8901_afe_sram_publish(b)==-ENODEV);
  mt8901_afe_sram_retire(b);mt8901_afe_sram_retire(NULL);
  assert(program_calls+irq_updates+stop_calls==writes);
  assert(mt8901_afe_sram_release(b)==-EBUSY && module_refs==1 && device_refs==1 && pm_refs==1);
  assert(mt8901_afe_sram_startup(&stream,&dai)==-EBUSY && force_suspend()==-EBUSY);
  _exit(0);
 }
 assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));empty();
 reset();init();b=mt8901_afe_sram_reserve(&device,3840);assert(!IS_ERR(b));
 assert(!mt8901_afe_sram_bind(b,&stream) && mt8901_afe_sram_bind(b,&stream)==-EBUSY);
 struct mt8901_afe_sram_endpoint endpoint;assert(!mt8901_afe_sram_endpoint(b,&endpoint,sizeof(endpoint)));
 struct mt8901_afe_sram_endpoint saved=endpoint;
 assert(mt8901_afe_sram_endpoint(b,&endpoint,sizeof(endpoint)-1)==-EINVAL);
 assert(!memcmp(&endpoint,&saved,sizeof(endpoint)));
 assert(mt8901_afe_sram_endpoint(b,&endpoint,sizeof(endpoint)+1)==-EINVAL);
 assert(!memcmp(&endpoint,&saved,sizeof(endpoint)));
 assert(endpoint.abi_version==2 && endpoint.rate==48000 && endpoint.channels==2 && endpoint.sample_bits==16);
 assert(endpoint.period_frames==480 && endpoint.periods==2 && !endpoint.memif && !endpoint.irq);
 assert(mt8901_afe_sram_startup(&stream,&dai)==-EBUSY);
 runtime.rate=44100;assert(mt8901_afe_sram_endpoint(b,&endpoint,sizeof(endpoint))==-EBUSY);
 assert(mt8901_afe_sram_publish(b)==-EBUSY && !barriers);runtime.rate=48000;
 runtime.running=true;assert(mt8901_afe_sram_endpoint(b,&endpoint,sizeof(endpoint))==-EBUSY);
 assert(mt8901_afe_sram_publish(b)==-EBUSY && !barriers);runtime.running=false;
 afe.memif[0].substream=NULL;assert(mt8901_afe_sram_endpoint(b,&endpoint,sizeof(endpoint))==-EBUSY);
 assert(mt8901_afe_sram_publish(b)==-EBUSY && !barriers);
 assert(!mt8901_afe_sram_release(b));empty();
 assert(!mt8901_afe_sram_startup(&stream,&dai));
 assert(!pthread_barrier_init(&rendezvous,NULL,8));pthread_t threads[8];
 for(unsigned i=0;i<8;i++)assert(!pthread_create(&threads[i],NULL,reserve_thread,(void *)(uintptr_t)i));
 for(unsigned i=0;i<8;i++)assert(!pthread_join(threads[i],NULL));
 for(unsigned i=0;i<8;i++)for(unsigned j=i+1;j<8;j++){
  u64 a=concurrent_views[i].cpu_address,b=concurrent_views[j].cpu_address;
  assert(a+3840<=b || b+3840<=a);
 }
 empty();assert(!pthread_barrier_destroy(&rendezvous));cleanup();assert(!pools);
 /* Full duplex must fit simultaneously, with one independently owned lease
  * per direction and playback IPC. No overlapping address ranges or votes.
  */
 reset();init();child=fork();assert(child>=0);
 if(!child) {
  struct mt8901_afe_sram_buffer *play=mt8901_afe_sram_reserve(&device,32768);
  struct mt8901_afe_sram_buffer *capture=mt8901_afe_sram_reserve(&device,32768);
  assert(!IS_ERR(play) && !IS_ERR(capture));
  assert(!mt8901_afe_sram_bind(play,&stream));
  struct mt8901_afe_sram_buffer *ipc=mt8901_afe_sram_reserve_ipc(play,2048);
  assert(!IS_ERR(ipc));
  struct snd_soc_dai cap_dai=dai;cap_dai.id=8;
  struct snd_soc_pcm_runtime cap_rtd=rtd;cap_rtd.cpu=&cap_dai;
  struct snd_pcm_substream cap_stream=stream;cap_stream.stream=1;cap_stream.rtd=&cap_rtd;
  afe.memif[8].substream=&cap_stream;
  assert(!mt8901_afe_sram_bind(capture,&cap_stream));
  assert(private.sram->memif[0]==play && private.sram->memif[8]==capture);
  struct mt8901_afe_sram_view a,b,c;
  assert(!mt8901_afe_sram_view(play,&a) && !mt8901_afe_sram_view(capture,&b) && !mt8901_afe_sram_view(ipc,&c));
  assert(a.cpu_address+a.bytes<=b.cpu_address && b.cpu_address+b.bytes<=c.cpu_address);
  assert(!mt8901_afe_sram_publish(play) && !mt8901_afe_sram_publish(capture) && !mt8901_afe_sram_publish_ipc(ipc));
  assert(!mt8901_afe_sram_allow_retention(play) && !mt8901_afe_sram_allow_retention(capture) && !mt8901_afe_sram_allow_retention(ipc));
  assert(atomic_read(&private.sram->users)==3 && atomic_read(&private.sram->retention_users)==3);
  for(unsigned cycle=0;cycle<32;cycle++) {
   device_lock(&device);assert(!mt8901_afe_sram_pm_prepare(&afe));device_unlock(&device);
   assert(!mt8901_afe_sram_suspend(play) && !mt8901_afe_sram_suspend(ipc));
   device_lock(&device);assert(mt8901_afe_sram_pm_save(&afe)==-EBUSY);device_unlock(&device);
   assert(!mt8901_afe_sram_suspend(capture));
   device_lock(&device);assert(!mt8901_afe_sram_pm_save(&afe));mt8901_afe_sram_pm_restore(&afe);device_unlock(&device);
   assert(!mt8901_afe_sram_resume(play) && !mt8901_afe_sram_resume(capture) && !mt8901_afe_sram_resume(ipc));
   device_lock(&device);mt8901_afe_sram_pm_complete(&afe);device_unlock(&device);
   assert(!atomic_read(&private.sram->sleeping_users));
  }
  _exit(0);
 }
 assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));empty();cleanup();
 puts("AFE SRAM owner: independent duplex leases/votes, 32 PM cycles, publication faults and concurrent ownership: PASS");
 return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='mt8901-sram-') as directory:
        directory = Path(directory)
        source = directory / 'sram.c'
        binary = directory / 'sram'
        source.write_text(code)
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        '-Wno-misleading-indentation', '-fsanitize=address,undefined',
                        '-pthread', '-g', str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
