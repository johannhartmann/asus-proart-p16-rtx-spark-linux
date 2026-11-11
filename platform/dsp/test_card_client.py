#!/usr/bin/env python3
"""Exercise the actual ALSA OPEN wrapper and its card-link ownership faults."""
from pathlib import Path
import subprocess
import tempfile


def main():
    source = Path(__file__).with_name('n1x_adsp.c').read_text()
    function = source[source.index('struct n1x_adsp_primary *n1x_adsp_primary_open_pcm('):
                      source.index('EXPORT_SYMBOL_GPL(n1x_adsp_primary_open_pcm);')]
    code = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
struct device_driver {int unused;};
struct device {struct device_driver *driver;};struct device_link {int unused;};
struct snd_pcm_substream {int stream;};
#define SNDRV_PCM_STREAM_CAPTURE 1
#define SNDRV_PCM_STREAM_PLAYBACK 0
struct n1x_adsp {int lock;bool capture;};static struct n1x_adsp context;
struct n1x_adsp_primary {struct n1x_adsp *dsp;struct device_link *card_link;struct snd_pcm_substream *substream;};
#define ERR_PTR(x) ((void *)(intptr_t)(x))
#define ERR_CAST(x) ((void *)(x))
#define IS_ERR(x) ((uintptr_t)(x)>=(uintptr_t)-4095)
#define IS_ERR_OR_NULL(x) (!(x)||IS_ERR(x))
#define WRITE_ONCE(x,v) ((x)=(v))
#define DL_FLAG_STATELESS 1
static unsigned locked;
static bool no_context;
static void *dev_get_drvdata(struct device *d) {(void)d;return no_context?NULL:&context;}
static void device_lock(struct device *d) {(void)d;assert(!locked);locked=1;}
static void device_unlock(struct device *d) {(void)d;assert(locked==1);locked=0;}
static void mutex_lock(int *lock) {assert(lock==&context.lock && locked==1);locked=2;}
static void mutex_unlock(int *lock) {assert(lock==&context.lock && locked==2);locked=1;}
static struct {struct device_driver driver;} n1x_adsp_driver;
static struct device dsp,card;static struct device_link link;
static struct snd_pcm_substream stream;static struct n1x_adsp_primary primary;
static unsigned refs,lookups,symbol_puts,opens,links,deletes;
static bool missing,link_error,card_null;static int card_error,open_error;
static struct device *mt8901_afe_pcm_card_device(struct snd_pcm_substream *s)
{assert(s==&stream);lookups++;if(card_error)return ERR_PTR(card_error);if(card_null)return NULL;refs++;return &card;}
static void *get_symbol(void) {return missing?NULL:(void *)mt8901_afe_pcm_card_device;}
#define symbol_get(n) ((typeof(&n))get_symbol())
#define symbol_put(n) (symbol_puts++)
static struct device_link *device_link_add(struct device *c,struct device *d,unsigned flags)
{assert(c==&card && d==&dsp && refs && flags==DL_FLAG_STATELESS);links++;return link_error?NULL:&link;}
static void put_device(struct device *d) {assert(d==&card && refs);refs--;}
static void device_link_del(struct device_link *p) {assert(p==&link && !refs);deletes++;}
static struct n1x_adsp_primary *n1x_adsp_primary_open(struct device *d)
{assert(d==&dsp && links && !refs);opens++;return open_error?ERR_PTR(open_error):&primary;}
''' + function + r'''
int main(void) {
 assert(IS_ERR(n1x_adsp_primary_open_pcm(NULL,&stream)));
 assert(IS_ERR(n1x_adsp_primary_open_pcm(&dsp,NULL)) && !lookups && !opens);
 for(unsigned fault=0;fault<10;fault++) {
  refs=lookups=symbol_puts=opens=links=deletes=0;missing=link_error=card_null=false;
  card_error=open_error=0;no_context=false;stream.stream=0;context.capture=false;dsp.driver=&n1x_adsp_driver.driver;primary.dsp=&context;primary.card_link=NULL;primary.substream=NULL;
  switch(fault){case 1:missing=true;break;case 2:card_error=-EBUSY;break;
   case 3:link_error=true;break;case 4:open_error=-EIO;break;case 5:card_null=true;break;case 6:context.capture=true;break;case 7:dsp.driver=NULL;break;case 8:no_context=true;break;case 9:context.capture=true;stream.stream=1;break;}
  struct n1x_adsp_primary *p=n1x_adsp_primary_open_pcm(&dsp,&stream);
  assert(!refs);
  if(!fault || fault==9){assert(p==&primary && p->card_link==&link && p->substream==&stream && !locked && opens==1 && links==1 && !deletes);}
  else {assert(IS_ERR(p) && !primary.card_link);
   if(fault==4)assert(opens==1 && deletes==1);
   else assert(!opens && !deletes);
  }
  assert(symbol_puts==(unsigned)!missing);
 }
 puts("DSP ALSA OPEN: actual card lookup, PM-link grant, preflight refusals and failed-OPEN link release: PASS");
}
'''
    with tempfile.TemporaryDirectory(prefix='n1x-card-client-') as directory:
        source, binary = Path(directory)/'test.c', Path(directory)/'test'
        source.write_text(code)
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
