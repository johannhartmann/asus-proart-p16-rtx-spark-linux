#!/usr/bin/env python3
"""Exercise actual AFE/DSP PCM callbacks with mocked ALSA, workqueue and IPC edges."""
from pathlib import Path
import re
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent


def main():
    source = re.sub(r'^#include.*\n', '', (HERE / 'mt8901-afe-dsp.c').read_text(), flags=re.M)
    header = re.sub(r'^#include.*\n', '', (HERE / 'mt8901-afe-sram.h').read_text(), flags=re.M)
    code = r'''
#define _DEFAULT_SOURCE
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "n1x_adsp_client.h"
typedef uint8_t u8;typedef uint32_t u32;typedef uint64_t u64;typedef unsigned long snd_pcm_uframes_t;
#define __iomem
#define GFP_KERNEL 0
#define module_param(a,b,c)
#define MODULE_PARM_DESC(a,b)
#define READ_ONCE(x) __atomic_load_n(&(x),__ATOMIC_SEQ_CST)
#define WRITE_ONCE(x,v) __atomic_store_n(&(x),(v),__ATOMIC_SEQ_CST)
#define smp_store_release(p,v) __atomic_store_n((p),(v),__ATOMIC_RELEASE)
#define smp_load_acquire(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
#define min(a,b) ((a)<(b)?(a):(b))
#define min_t(t,a,b) min((t)(a),(t)(b))
#define ERR_PTR(e) ((void *)(intptr_t)(e))
#define PTR_ERR(p) ((long)(intptr_t)(p))
#define IS_ERR(p) ((uintptr_t)(p)>=(uintptr_t)-4095)
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define SNDRV_PCM_STREAM_PLAYBACK 0
#define SNDRV_PCM_STREAM_CAPTURE 1
#define SNDRV_PCM_INFO_PAUSE 1U
#define SNDRV_PCM_INFO_RESUME 2U
#define SNDRV_PCM_INFO_NO_PERIOD_WAKEUP 4U
#define SNDRV_PCM_POS_XRUN (~0UL)
#define SNDRV_PCM_TRIGGER_START 1
#define SNDRV_PCM_TRIGGER_STOP 2
#define SNDRV_PCM_TRIGGER_SUSPEND 3
#define MT8901_AFE_MEMIF_DL0 0
#define MT8901_AFE_MEMIF_DL1 1
#define MT8901_AFE_MEMIF_UL1 8
#define AFE_PCM_NAME "mtk-afe-pcm"
struct device {int id;};
struct snd_pcm_hardware {unsigned channels_max,buffer_bytes_max,period_bytes_max,info;};
struct control {snd_pcm_uframes_t appl_ptr;};
struct snd_pcm_runtime {struct snd_pcm_hardware hw;unsigned rate,channels,sample_bits,periods;
 snd_pcm_uframes_t period_size,buffer_size,boundary;struct control *control;void *dma_area;};
struct card {int sync_irq;};struct snd_pcm {bool nonatomic;struct card *card;};
struct snd_soc_dai {int id;struct device *dev;void *data;};
struct snd_soc_pcm_runtime {struct snd_soc_dai *cpu;};
struct snd_pcm_substream {int stream;struct snd_pcm_runtime *runtime;struct snd_pcm *pcm;struct snd_soc_pcm_runtime *rtd;};
struct mt8901_afe_dsp;
struct mt8901_afe_private {void *sram;struct mt8901_afe_dsp *dsp[2];};
struct mtk_base_afe {struct device *dev;struct mt8901_afe_private *platform_priv;};
struct snd_soc_component {int unused;};
struct snd_soc_component_driver {const char *name;
 snd_pcm_uframes_t (*pointer)(struct snd_soc_component *,struct snd_pcm_substream *);
 int (*ack)(struct snd_soc_component *,struct snd_pcm_substream *);
 int (*sync_stop)(struct snd_soc_component *,struct snd_pcm_substream *);
 int (*pcm_new)(struct snd_soc_component *,struct snd_soc_pcm_runtime *);
 int (*probe)(struct snd_soc_component *);};
typedef pthread_mutex_t spinlock_t;
#define spin_lock_init(p) assert(!pthread_mutex_init(p,NULL))
#define spin_lock_irqsave(p,f) ((f)=0,assert(!pthread_mutex_lock(p)))
#define spin_unlock_irqrestore(p,f) ((void)(f),assert(!pthread_mutex_unlock(p)))
struct work_struct {void (*fn)(struct work_struct *);bool pending,running;};
static pthread_mutex_t work_lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t work_idle=PTHREAD_COND_INITIALIZER;
static pthread_barrier_t entered,released;
static atomic_bool cancel_waiting,primary_dead;
static bool position_block;
static unsigned allocations,symbol_refs,device_refs,missing,open_error,abi_value;
static unsigned reserves,binds,releases,configures,prepares,views,listens,detaches,commits,starts,stops;
static atomic_uint closes,elapsed,xruns;
static unsigned cancel_calls,sync_irqs,last_commit,probes;
static unsigned fail;static bool transfer_on_error;
static int commit_error,start_error,stop_error,position_error,engine_error;
static unsigned engine_starts;
static struct n1x_adsp_pcm_position position_value;
static struct device afe_dev={1},dsp_dev={2};
static unsigned char staging[3840],host[3840];
struct n1x_adsp_primary {int unused;};static struct n1x_adsp_primary primary;
struct mt8901_afe_sram_buffer {bool published;};static struct mt8901_afe_sram_buffer lease;
static struct control control;
static struct snd_pcm_runtime runtime;
static struct card card={77};static struct snd_pcm pcm={true,&card};
static struct snd_soc_dai dai;
static struct snd_soc_pcm_runtime rtd;
static struct snd_pcm_substream stream,other;
static struct mt8901_afe_private priv;
static struct mtk_base_afe afe;
static struct snd_soc_pcm_runtime *snd_soc_substream_to_rtd(struct snd_pcm_substream *s) {return s->rtd;}
static struct snd_soc_dai *snd_soc_rtd_to_cpu(struct snd_soc_pcm_runtime *r,unsigned i) {assert(!i);return r->cpu;}
static struct mtk_base_afe *snd_soc_dai_get_drvdata(struct snd_soc_dai *d) {return d->data;}
static size_t frames_to_bytes(struct snd_pcm_runtime *r,snd_pcm_uframes_t frames)
{return frames*r->channels*(r->sample_bits/8);}
static snd_pcm_uframes_t bytes_to_frames(struct snd_pcm_runtime *r,size_t bytes)
{return bytes/(r->channels*(r->sample_bits/8));}
static size_t snd_pcm_lib_buffer_bytes(struct snd_pcm_substream *s)
{return frames_to_bytes(s->runtime,s->runtime->buffer_size);}
static size_t mt8901_afe_sram_size(struct mtk_base_afe *a) {assert(a==&afe);return 81920;}
static void (*dma_hook)(void);
static void dma_rmb(void) {atomic_thread_fence(memory_order_acquire);if(dma_hook){void (*fn)(void)=dma_hook;dma_hook=NULL;fn();}}
static void *allocate(size_t bytes) {void *p=calloc(1,bytes);assert(p);allocations++;return p;}
#define kzalloc_obj(x) allocate(sizeof(x))
static void kfree(void *p) {assert(p && allocations);allocations--;free(p);}
static struct device *n1x_adsp_find_device(struct device *consumer,const char *name)
{assert(consumer==afe.dev && !strcmp(name,stream.stream ? "NVDA8301" : "NVDA8303"));if(fail==1)return NULL;device_refs++;return &dsp_dev;}
static void put_device(struct device *d) {assert(d==&dsp_dev && device_refs);device_refs--;}
static void synchronize_irq(int irq) {assert(irq==77);sync_irqs++;}
static void init_work(struct work_struct *w,void (*fn)(struct work_struct *)) {w->fn=fn;}
#define INIT_WORK(w,f) init_work(w,f)
static bool schedule_work(struct work_struct *w)
{assert(!pthread_mutex_lock(&work_lock));w->pending=true;assert(!pthread_mutex_unlock(&work_lock));return true;}
static bool cancel_work_sync(struct work_struct *w)
{assert(!pthread_mutex_lock(&work_lock));cancel_calls++;w->pending=false;
 atomic_store(&cancel_waiting,true);while(w->running)assert(!pthread_cond_wait(&work_idle,&work_lock));
 assert(!pthread_mutex_unlock(&work_lock));return true;}
static void *run_work(void *ptr)
{struct work_struct *w=ptr;assert(!pthread_mutex_lock(&work_lock));assert(w->pending);w->pending=false;w->running=true;
 assert(!pthread_mutex_unlock(&work_lock));w->fn(w);assert(!pthread_mutex_lock(&work_lock));w->running=false;
 assert(!pthread_cond_broadcast(&work_idle));assert(!pthread_mutex_unlock(&work_lock));return NULL;}
static void snd_pcm_period_elapsed(struct snd_pcm_substream *s)
{assert(s==&stream && !atomic_load(&primary_dead));atomic_fetch_add(&elapsed,1);}
static void snd_pcm_stop_xrun(struct snd_pcm_substream *s)
{assert(s==&stream && !atomic_load(&primary_dead));atomic_fetch_add(&xruns,1);}
static snd_pcm_uframes_t mtk_afe_pcm_pointer(struct snd_soc_component *c,struct snd_pcm_substream *s)
{(void)c;assert(s==&stream || s==&other);return 37;}
static int mtk_afe_pcm_new(struct snd_soc_component *c,struct snd_soc_pcm_runtime *r)
{(void)c;(void)r;return 0;}
static int original_probe(struct snd_soc_component *c) {(void)c;probes++;return 0;}
static const struct snd_soc_component_driver mtk_afe_pcm_platform={.probe=original_probe};
static void (*listener)(void *,const struct n1x_adsp_pcm_position *,int);
static void *listener_data;
''' + header + r'''
u32 n1x_adsp_primary_abi(void) {return abi_value;}
struct n1x_adsp_primary *n1x_adsp_primary_open_pcm(struct device *d,struct snd_pcm_substream *s)
{assert(d==&dsp_dev && s==&stream);if(open_error)return ERR_PTR(-(int)open_error);atomic_store(&primary_dead,false);return &primary;}
int n1x_adsp_primary_rebind(struct n1x_adsp_primary *p,struct snd_pcm_substream *s)
{assert(p==&primary && s==&stream);return lease.published?0:-ENOENT;}
int n1x_adsp_primary_configure(struct n1x_adsp_primary *p,const struct n1x_adsp_primary_pcm_params *params,
 struct mt8901_afe_sram_buffer **buffer)
{assert(p==&primary && ((*buffer==&lease && !lease.published) || (!*buffer && lease.published)) && binds==1);configures++;
 assert(params->rate==48000 && params->channels==2 && params->sample_bits==runtime.sample_bits && params->period_frames==runtime.period_size && params->periods==2);
 if(fail==4 && !transfer_on_error)return -EIO;lease.published=true;*buffer=NULL;return fail==4?-EIO:0;}
int n1x_adsp_primary_prepare_pcm(struct n1x_adsp_primary *p)
{assert(p==&primary && lease.published);prepares++;return fail==5?-EIO:0;}
int n1x_adsp_primary_pcm_view(struct n1x_adsp_primary *p,struct n1x_adsp_primary_pcm_view *v)
{assert(p==&primary);views++;if(fail==6)return -EIO;*v=(struct n1x_adsp_primary_pcm_view){host,fail==7?3839:sizeof(host)};return 0;}
int n1x_adsp_primary_set_period(struct n1x_adsp_primary *p,
 void (*fn)(void *,const struct n1x_adsp_pcm_position *,int),void *data)
{assert(p==&primary && !atomic_load(&primary_dead));if(!fn){listener=NULL;listener_data=NULL;detaches++;return 0;}
 listens++;if(fail==8)return -EIO;assert(!listener);listener=fn;listener_data=data;return 0;}
int n1x_adsp_primary_commit(struct n1x_adsp_primary *p,u32 offset)
{assert(p==&primary && !atomic_load(&primary_dead));commits++;last_commit=offset;return commit_error;}
int n1x_adsp_primary_start(struct n1x_adsp_primary *p) {assert(p==&primary);starts++;return start_error;}
int n1x_adsp_primary_stop(struct n1x_adsp_primary *p) {assert(p==&primary);stops++;if(!stop_error){listener=NULL;listener_data=NULL;}return stop_error;}
int mt8901_afe_sram_start_pcm(struct snd_pcm_substream *s,struct snd_soc_dai *d)
{assert(s==&stream && d==&dai && starts==engine_starts+1 && !start_error);engine_starts++;return engine_error;}
int n1x_adsp_primary_position(struct n1x_adsp_primary *p,struct n1x_adsp_pcm_position *v)
{assert(p==&primary && !atomic_load(&primary_dead));if(position_block){
 int r=pthread_barrier_wait(&entered);assert(r==0 || r==PTHREAD_BARRIER_SERIAL_THREAD);
 r=pthread_barrier_wait(&released);assert(r==0 || r==PTHREAD_BARRIER_SERIAL_THREAD);}
 assert(!atomic_load(&primary_dead));if(position_error)return position_error;*v=position_value;return 0;}
int n1x_adsp_primary_close(struct n1x_adsp_primary *p)
{assert(p==&primary && !listener && !listener_data);atomic_store(&primary_dead,true);atomic_fetch_add(&closes,1);return fail==9?-EIO:0;}
struct mt8901_afe_sram_buffer *mt8901_afe_sram_reserve(struct device *d,size_t bytes)
{assert(d==&afe_dev && bytes==runtime.hw.buffer_bytes_max);reserves++;return fail==2?ERR_PTR(-ENOMEM):&lease;}
int mt8901_afe_sram_bind(struct mt8901_afe_sram_buffer *b,struct snd_pcm_substream *s)
{assert(b==&lease && s==&stream && !lease.published);binds++;return fail==3?-EBUSY:0;}
int mt8901_afe_sram_release(struct mt8901_afe_sram_buffer *b)
{assert(b==&lease && !lease.published);releases++;return 0;}
static void *get_symbol(const char *name)
{const char *names[]={"abi","open_pcm","configure","prepare_pcm","pcm_view","commit","start","stop","set_period","position","close","rebind"};
 void *ops[]={(void *)n1x_adsp_primary_abi,(void *)n1x_adsp_primary_open_pcm,(void *)n1x_adsp_primary_configure,(void *)n1x_adsp_primary_prepare_pcm,
 (void *)n1x_adsp_primary_pcm_view,(void *)n1x_adsp_primary_commit,(void *)n1x_adsp_primary_start,(void *)n1x_adsp_primary_stop,
 (void *)n1x_adsp_primary_set_period,(void *)n1x_adsp_primary_position,(void *)n1x_adsp_primary_close,(void *)n1x_adsp_primary_rebind};
 assert(!strncmp(name,"n1x_adsp_primary_",17));name+=17;
 for(unsigned i=0;i<12;i++)if(!strcmp(name,names[i])){if(missing==i+1)return NULL;symbol_refs++;return ops[i];}assert(0);return NULL;}
static void put_symbol(const char *name) {(void)name;assert(symbol_refs);symbol_refs--;}
#define symbol_get(n) ((typeof(&n))get_symbol(#n))
#define symbol_put(n) put_symbol(#n)
''' + source + r'''
static void reset(void)
{
 assert(!allocations && !symbol_refs && !device_refs && !priv.dsp[stream.stream]);
 runtime=(struct snd_pcm_runtime){.hw={8,512*1024,256*1024,7},.rate=48000,.channels=2,.sample_bits=16,
 .periods=2,.period_size=480,.buffer_size=960,.boundary=3840,.control=&control,.dma_area=staging};
 control.appl_ptr=0;pcm.nonatomic=true;dai=(struct snd_soc_dai){0,&afe_dev,&afe};rtd.cpu=&dai;
 stream=(struct snd_pcm_substream){.runtime=&runtime,.pcm=&pcm,.rtd=&rtd};other=stream;
 priv=(struct mt8901_afe_private){.sram=(void *)1};afe=(struct mtk_base_afe){&afe_dev,&priv};
 memset(staging,0,sizeof(staging));memset(host,0,sizeof(host));lease.published=false;
 reserves=binds=releases=configures=prepares=views=listens=detaches=commits=starts=stops=0;
 cancel_calls=sync_irqs=last_commit=probes=missing=open_error=fail=0;commit_error=start_error=stop_error=position_error=0;
 engine_error=0;engine_starts=0;
 atomic_store(&closes,0);atomic_store(&elapsed,0);atomic_store(&xruns,0);atomic_store(&primary_dead,false);atomic_store(&cancel_waiting,false);
 position_block=transfer_on_error=false;position_value=(struct n1x_adsp_pcm_position){.valid=true,.byte_offset=1920};
 listener=NULL;listener_data=NULL;dma_hook=NULL;dsp_playback=true;dsp_capture=false;abi_value=N1X_ADSP_PRIMARY_ABI;
}
static void setup(void) {reset();assert(!mt8901_afe_dsp_startup(&stream,&dai));assert(priv.dsp[stream.stream] && symbol_refs==12);}
static void prepare(void) {assert(!mt8901_afe_dsp_prepare(&stream,&dai));assert(listener && priv.dsp[stream.stream]->prepared && configures==1);}
static void shutdown(void)
{mt8901_afe_dsp_shutdown(&stream,&dai);assert(!allocations && !symbol_refs && !device_refs && !priv.dsp[stream.stream] && !listener);}
static void *free_thread(void *unused)
{(void)unused;assert(!mt8901_afe_dsp_hw_free(&stream,&dai));return NULL;}
static void capture_overrun_during_copy(void)
{position_value.byte_offset=0;position_value.at_end=true;listener(listener_data,&position_value,0);}
int main(void)
{
 reset();dsp_playback=false;assert(!mt8901_afe_dsp_startup(&stream,&dai) && !priv.dsp[stream.stream] && !symbol_refs);
 assert(mt8901_afe_dsp_pointer(NULL,&stream)==37 && !mt8901_afe_dsp_ack(NULL,&stream));
 assert(!mt8901_afe_dsp_sync_stop(NULL,&stream) && sync_irqs==1);
 assert(!mt8901_afe_dsp_platform.probe(NULL) && probes==1);
 for(unsigned i=1;i<=11;i++){reset();missing=i;assert(mt8901_afe_dsp_startup(&stream,&dai)==-EOPNOTSUPP && !allocations && !symbol_refs && !priv.dsp[stream.stream]);}
 reset();abi_value++;assert(mt8901_afe_dsp_startup(&stream,&dai)==-EOPNOTSUPP && !allocations && !symbol_refs);
 reset();pcm.nonatomic=false;assert(mt8901_afe_dsp_startup(&stream,&dai)==-EOPNOTSUPP && !allocations);
 reset();priv.sram=NULL;assert(mt8901_afe_dsp_startup(&stream,&dai)==-EOPNOTSUPP && !allocations);
 reset();dai.id=2;assert(!mt8901_afe_dsp_startup(&stream,&dai) && !priv.dsp[stream.stream]);
 reset();stream.stream=1;assert(!mt8901_afe_dsp_startup(&stream,&dai) && !priv.dsp[stream.stream]);
 reset();fail=1;assert(mt8901_afe_dsp_startup(&stream,&dai)==-ENODEV && !allocations && !symbol_refs && !device_refs);
 reset();open_error=EIO;assert(mt8901_afe_dsp_startup(&stream,&dai)==-EIO && !allocations && !symbol_refs && !device_refs);
 setup();assert(runtime.hw.channels_max==2 && runtime.hw.buffer_bytes_max==32768 && runtime.hw.period_bytes_max==16384 && !runtime.hw.info);
 assert(!mt8901_afe_dsp_active(&other) && mt8901_afe_dsp_active(&stream));
 assert(!mt8901_afe_dsp_hw_params(&stream) && mt8901_afe_dsp_pointer(NULL,&stream)==0);
 assert(mt8901_afe_dsp_ack(NULL,&stream)==-EBADFD);prepare();assert(!mt8901_afe_dsp_prepare(&stream,&dai) && prepares==1 && listens==1);
 assert(mt8901_afe_dsp_hw_params(&stream)==-EALREADY && mt8901_afe_dsp_pointer(NULL,&stream)==480);
 position_value.valid=false;assert(!mt8901_afe_dsp_pointer(NULL,&stream));position_value.valid=true;
 assert(mt8901_afe_dsp_trigger(&stream,99)==-EINVAL && !starts && !stops);
 memset(staging,0x11,sizeof(staging));control.appl_ptr=480;assert(!mt8901_afe_dsp_ack(NULL,&stream) && last_commit==1920);
 for(unsigned i=0;i<3840;i++)assert(host[i]==(i<1920?0x11:0));
 memset(staging,0x22,sizeof(staging));control.appl_ptr=960;assert(!mt8901_afe_dsp_ack(NULL,&stream) && last_commit==3840);
 for(unsigned i=0;i<3840;i++)assert(host[i]==(i<1920?0x11:0x22));
 assert(!mt8901_afe_dsp_ack(NULL,&stream) && commits==2);
 assert(mt8901_afe_dsp_prepare(&stream,&dai)==-EALREADY);
 control.appl_ptr=959;assert(mt8901_afe_dsp_ack(NULL,&stream)==-EINVAL && commits==2);
 control.appl_ptr=3840;assert(mt8901_afe_dsp_ack(NULL,&stream)==-EINVAL && commits==2);
 priv.dsp[stream.stream]->appl_ptr=3600;control.appl_ptr=240;memset(staging,0x33,sizeof(staging));
 assert(!mt8901_afe_dsp_ack(NULL,&stream) && last_commit==960);
 for(unsigned i=0;i<960;i++)assert(host[i]==0x33);for(unsigned i=2880;i<3840;i++)assert(host[i]==0x33);
 assert(!mt8901_afe_dsp_trigger(&stream,SNDRV_PCM_TRIGGER_START) && starts==1);

 position_value.byte_offset=480;listener(listener_data,&position_value,0);assert(!priv.dsp[stream.stream]->period_work.pending);
 position_value.byte_offset=960;position_value.counter=999;listener(listener_data,&position_value,0);assert(!priv.dsp[stream.stream]->period_work.pending);
 position_value.byte_offset=1920;listener(listener_data,&position_value,0);assert(priv.dsp[stream.stream]->period_work.pending);
 run_work(&priv.dsp[stream.stream]->period_work);assert(atomic_load(&elapsed)==1);
 listener(listener_data,&position_value,0);assert(!priv.dsp[stream.stream]->period_work.pending);
 position_value.byte_offset=0;position_value.at_end=true;listener(listener_data,&position_value,0);
 run_work(&priv.dsp[stream.stream]->period_work);assert(atomic_load(&elapsed)==2);
 position_value.at_end=false;listener(listener_data,&position_value,0);assert(!priv.dsp[stream.stream]->period_work.pending);
 position_value.byte_offset=1920;listener(listener_data,&position_value,0);
 position_value.byte_offset=0;position_value.at_end=true;listener(listener_data,&position_value,0);
 run_work(&priv.dsp[stream.stream]->period_work);assert(atomic_load(&elapsed)==3);

 position_error=-EPROTO;listener(listener_data,&position_value,-EPROTO);run_work(&priv.dsp[stream.stream]->period_work);assert(atomic_load(&xruns)==1);
 position_error=0;assert(!mt8901_afe_dsp_trigger(&stream,SNDRV_PCM_TRIGGER_STOP) && stops==1);
 mt8901_afe_dsp_period(priv.dsp[stream.stream],&position_value,0);assert(!mt8901_afe_dsp_sync_stop(NULL,&stream));assert(!priv.dsp[stream.stream]->period_work.pending);
 assert(!mt8901_afe_dsp_hw_free(&stream,&dai) && atomic_load(&closes)==1 && detaches==1);
 assert(!mt8901_afe_dsp_hw_free(&stream,&dai) && atomic_load(&closes)==1);shutdown();
 for(unsigned stage=2;stage<=8;stage++)for(unsigned transferred=0;transferred<(stage==4?2U:1U);transferred++){
  setup();fail=stage;transfer_on_error=transferred;int ret=mt8901_afe_dsp_prepare(&stream,&dai);assert(ret<0);
  assert(!priv.dsp[stream.stream]->prepared && !listener);
  if(stage==2){assert(!configures && !releases);fail=0;prepare();}
  else {assert(priv.dsp[stream.stream]->error==ret);assert(mt8901_afe_dsp_prepare(&stream,&dai)==ret);}
  assert(releases==(unsigned)(stage==3 || (stage==4 && !transferred)));
  fail=0;shutdown();assert(atomic_load(&closes)==1);
 }
 setup();prepare();commit_error=-EIO;control.appl_ptr=480;
 assert(mt8901_afe_dsp_ack(NULL,&stream)==-EIO && priv.dsp[stream.stream]->appl_ptr==0 && commits==1);
 assert(mt8901_afe_dsp_ack(NULL,&stream)==-EIO && commits==1);shutdown();
 setup();prepare();start_error=-ETIMEDOUT;assert(mt8901_afe_dsp_trigger(&stream,SNDRV_PCM_TRIGGER_START)==-ETIMEDOUT && !priv.dsp[stream.stream]->running && !engine_starts);
 assert(mt8901_afe_dsp_pointer(NULL,&stream)==SNDRV_PCM_POS_XRUN);shutdown();
 setup();prepare();engine_error=-EIO;
 assert(mt8901_afe_dsp_trigger(&stream,SNDRV_PCM_TRIGGER_START)==-EIO && starts==1 && engine_starts==1 && stops==1 && !priv.dsp[stream.stream]->running);
 assert(mt8901_afe_dsp_pointer(NULL,&stream)==SNDRV_PCM_POS_XRUN);shutdown();
 setup();prepare();engine_error=-EIO;stop_error=-ETIMEDOUT;
 assert(mt8901_afe_dsp_trigger(&stream,SNDRV_PCM_TRIGGER_START)==-ETIMEDOUT && stops==1 && !priv.dsp[stream.stream]->running);shutdown();
 setup();prepare();stop_error=-EIO;assert(mt8901_afe_dsp_trigger(&stream,SNDRV_PCM_TRIGGER_SUSPEND)==-EIO);shutdown();
 setup();prepare();fail=9;assert(mt8901_afe_dsp_hw_free(&stream,&dai)==-EIO && atomic_load(&closes)==1);shutdown();
 setup();prepare();assert(!mt8901_afe_dsp_trigger(&stream,SNDRV_PCM_TRIGGER_START));
 assert(!pthread_barrier_init(&entered,NULL,2) && !pthread_barrier_init(&released,NULL,2));
 position_block=true;listener(listener_data,&position_value,0);pthread_t worker,closer;
 assert(!pthread_create(&worker,NULL,run_work,&priv.dsp[stream.stream]->period_work));
 int r=pthread_barrier_wait(&entered);assert(r==0 || r==PTHREAD_BARRIER_SERIAL_THREAD);
 assert(!pthread_create(&closer,NULL,free_thread,NULL));
 while(!atomic_load(&cancel_waiting))sched_yield();assert(!atomic_load(&closes) && !atomic_load(&primary_dead));
 r=pthread_barrier_wait(&released);assert(r==0 || r==PTHREAD_BARRIER_SERIAL_THREAD);
 assert(!pthread_join(worker,NULL) && !pthread_join(closer,NULL));
 assert(atomic_load(&closes)==1 && !listener && !listener_data);shutdown();
 assert(!pthread_barrier_destroy(&entered) && !pthread_barrier_destroy(&released));
 /* ALSA HW_FREE/HW_PARAMS is legal without closing the file. Rebind the
  * existing lease while changing container width and period geometry.
  */
 setup();prepare();assert(!mt8901_afe_dsp_hw_free(&stream,&dai));
 runtime.sample_bits=32;runtime.period_size=240;runtime.buffer_size=480;
 assert(!mt8901_afe_dsp_hw_params(&stream) && !priv.dsp[0]->closing);
 assert(!mt8901_afe_dsp_prepare(&stream,&dai) && configures==2 && reserves==1 && binds==1);
 shutdown();assert(atomic_load(&closes)==2);
 /* Capture visibility follows the copied DSP producer, not a DMA cursor. */
 reset();dsp_capture=true;stream.stream=SNDRV_PCM_STREAM_CAPTURE;dai.id=MT8901_AFE_MEMIF_UL1;
 assert(!mt8901_afe_dsp_startup(&stream,&dai));prepare();
 assert(priv.dsp[1]->capture && !priv.dsp[0]);
 assert(!mt8901_afe_dsp_trigger(&stream,SNDRV_PCM_TRIGGER_START) && !commits);
 memset(host,0x11,1920);position_value.byte_offset=1920;
 listener(listener_data,&position_value,0);
 assert(!mt8901_afe_dsp_pointer(NULL,&stream) && !staging[0]);
 run_work(&priv.dsp[1]->period_work);
 assert(mt8901_afe_dsp_pointer(NULL,&stream)==480 && atomic_load(&elapsed)==1);
 for(unsigned i=0;i<1920;i++)assert(staging[i]==0x11);
 memset(host+1920,0x22,1920);position_value.byte_offset=0;position_value.at_end=true;
 listener(listener_data,&position_value,0);run_work(&priv.dsp[1]->period_work);
 assert(!mt8901_afe_dsp_pointer(NULL,&stream) && atomic_load(&elapsed)==2);
 for(unsigned i=1920;i<3840;i++)assert(staging[i]==0x22);
 position_value.at_end=false;position_value.byte_offset=960;memset(host,0x33,960);
 listener(listener_data,&position_value,0);run_work(&priv.dsp[1]->period_work);
 assert(mt8901_afe_dsp_pointer(NULL,&stream)==240 && atomic_load(&elapsed)==2);
 position_value.byte_offset=1920;memset(host+960,0x44,960);
 listener(listener_data,&position_value,0);run_work(&priv.dsp[1]->period_work);
 assert(atomic_load(&elapsed)==3 && mt8901_afe_dsp_pointer(NULL,&stream)==480);
 for(unsigned i=0;i<1920;i++)assert(staging[i]==(i<960?0x33:0x44));
 assert(!mt8901_afe_dsp_ack(NULL,&stream) && !commits);
 /* A whole uncopied ring is an overrun; never expose overwritten samples. */
 position_value.at_end=true;position_value.byte_offset=0;listener(listener_data,&position_value,0);
 position_value.at_end=false;position_value.byte_offset=1920;listener(listener_data,&position_value,0);
 assert(mt8901_afe_dsp_pointer(NULL,&stream)==SNDRV_PCM_POS_XRUN);
 run_work(&priv.dsp[1]->period_work);assert(atomic_load(&xruns)==1);
 assert(!mt8901_afe_dsp_trigger(&stream,SNDRV_PCM_TRIGGER_STOP));
 assert(!mt8901_afe_dsp_sync_stop(NULL,&stream));
 assert(!mt8901_afe_dsp_prepare(&stream,&dai) && !priv.dsp[1]->notification_error);
 assert(!mt8901_afe_dsp_pointer(NULL,&stream) && !priv.dsp[1]->capture_pending_bytes);
 assert(!mt8901_afe_dsp_trigger(&stream,SNDRV_PCM_TRIGGER_START));
 position_value.at_end=false;position_value.byte_offset=1920;
 listener(listener_data,&position_value,0);dma_hook=capture_overrun_during_copy;
 run_work(&priv.dsp[1]->period_work);
 assert(atomic_load(&xruns)==2 && !priv.dsp[1]->capture_offset);
 assert(mt8901_afe_dsp_pointer(NULL,&stream)==SNDRV_PCM_POS_XRUN);
 shutdown();
 puts("AFE DSP frontend: playback/capture ring copies, overrun recovery, HW_FREE reconfiguration and close/work lifetime: PASS");
 return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='mt8901-dsp-frontend-') as directory:
        directory = Path(directory)
        path = directory / 'frontend.c'
        path.write_text(code)
        binary = directory / 'frontend'
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        '-Wno-unused-parameter', '-Wno-misleading-indentation',
                        '-fsanitize=address,undefined', '-pthread', '-g',
                        '-I', str(HERE.parent), str(path), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=20)


if __name__ == '__main__':
    main()
