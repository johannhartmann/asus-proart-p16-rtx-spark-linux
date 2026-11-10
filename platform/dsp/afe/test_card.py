#!/usr/bin/env python3
"""Test actual ASoC auxiliary DSP binding, scoped lookup and probe unwinding."""
from pathlib import Path
import subprocess
import tempfile


def main():
    source = '\n'.join(line for line in Path(__file__).with_name('mt8901-dsp-card.h').read_text().splitlines()
                       if not line.startswith('#'))
    code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define GFP_KERNEL 0
#define EPROBE_DEFER 517
struct device {struct device *parent;unsigned refs,index;};
struct snd_soc_component {const char *name;};
struct snd_soc_aux_dev {struct {const char *name;} dlc;};
struct snd_soc_card {struct device *dev;struct snd_soc_aux_dev *aux_dev;unsigned num_aux_devs;};
static struct device parent,card_dev={.parent=&parent};
static struct device devices[3];
static struct snd_soc_component components[3]={{"DSP1"},{"DSP2"},{"DSP3"}};
static void *managed[4];static unsigned count,step,fault,missing,unready,lookups;
static void *devm_kcalloc(struct device *d,size_t n,size_t bytes,int flags)
{assert(d==&card_dev && flags==GFP_KERNEL);if(++step==fault)return NULL;
 void *p=calloc(n,bytes);assert(p && count<4);managed[count++]=p;return p;}
static char *devm_kstrdup(struct device *d,const char *name,int flags)
{assert(d==&card_dev && flags==GFP_KERNEL);if(++step==fault)return NULL;
 char *p=strdup(name);assert(p && count<4);managed[count++]=p;return p;}
static struct device *n1x_adsp_find_device(struct device *d,const char *hid)
{assert(d==&parent && !strncmp(hid,"NVDA830",7));unsigned i=hid[7]-'1';assert(i<3);lookups++;
 if(missing==i+1)return NULL;devices[i].refs++;return &devices[i];}
static struct snd_soc_component *snd_soc_lookup_component(struct device *d,const char *name)
{assert(d->refs==1 && !strcmp(name,"n1x-adsp"));return unready==d->index+1?NULL:&components[d->index];}
static void put_device(struct device *d){assert(d->refs==1);d->refs--;}
''' + source + r'''
static void reset(void)
{while(count)free(managed[--count]);step=fault=missing=unready=lookups=0;
 for(unsigned i=0;i<3;i++){assert(!devices[i].refs);devices[i].index=i;}}
int main(void)
{
 struct snd_soc_aux_dev old[2]={{{"codec0"}},{{"codec1"}}};
 struct snd_soc_card card={&card_dev,old,2};
 reset();assert(!mt8901_card_add_dsps(&card,false) && !count && !lookups && card.aux_dev==old);
 for(unsigned f=1;f<=4;f++){
  reset();fault=f;card=(struct snd_soc_card){&card_dev,old,2};
  assert(mt8901_card_add_dsps(&card,true)==-ENOMEM && card.aux_dev==old && card.num_aux_devs==2);
 }
 for(unsigned i=1;i<=3;i++)for(unsigned phase=0;phase<2;phase++){
  reset();if(phase)unready=i;else missing=i;card=(struct snd_soc_card){&card_dev,old,2};
  assert(mt8901_card_add_dsps(&card,true)==-EPROBE_DEFER && card.aux_dev==old && card.num_aux_devs==2);
 }
 reset();assert(!mt8901_card_add_dsps(&card,true) && card.num_aux_devs==5 && count==4 && lookups==3);
 assert(!strcmp(card.aux_dev[0].dlc.name,"codec0") && !strcmp(card.aux_dev[1].dlc.name,"codec1"));
 for(unsigned i=0;i<3;i++)assert(!strcmp(card.aux_dev[2+i].dlc.name,components[i].name) && !devices[i].refs);
 reset();puts("ASoC DSP card: scoped suppliers, preserved codec auxiliaries, deferred firmware readiness and allocation faults: PASS");
}
'''
    with tempfile.TemporaryDirectory(prefix='mt8901-card-') as tmp:
        test, binary = Path(tmp)/'test.c', Path(tmp)/'test'
        test.write_text(code)
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation',
                        '-fsanitize=address,undefined', str(test), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
