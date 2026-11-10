#!/usr/bin/env python3
"""Exercise actual probe-time provider acquisition and devres unwinding."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent


def main():
    source = (ROOT/'n1x_adsp.c').read_text()
    functions = source[source.index('static void n1x_adsp_put_provider('):
                       source.index('static void n1x_adsp_del_link(')]
    code = r'''
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <errno.h>
#include "n1x_sroot_client.h"
#define EPROBE_DEFER 517
#define ERR_PTR(e) ((void *)(intptr_t)(e))
#define IS_ERR(p) ((uintptr_t)(p)>=(uintptr_t)-4095)
#define PTR_ERR(p) ((long)(intptr_t)(p))
struct device {int unused;};
struct n1x_sroot_client {int unused;};
struct n1x_adsp {struct device *dev;const struct n1x_sroot_client_ops *sroot_ops;
 struct n1x_sroot_client *sroot_client;const struct n1x_sroot_client_sleep_ops *sleep_ops;};
static struct device device;
static struct n1x_sroot_client client;
static unsigned symbols,handles,fault;
static bool published;
static void (*cleanup)(void *);
static struct n1x_sroot_client *get_client(struct device *dev)
{assert(dev==&device && symbols==1);if(fault==2)return ERR_PTR(-ENOTUNIQ);handles++;return &client;}
static int put_client(struct n1x_sroot_client *c)
{assert(c==&client && handles==1 && symbols==1);if(published)return -EBUSY;handles--;return 0;}
static const struct n1x_sroot_client_ops ops={.get=get_client,.put=put_client};
static const struct n1x_sroot_client_sleep_ops sleep_ops={.client=&ops};
static const struct n1x_sroot_client_sleep_ops *get_ops(void){assert(symbols==1);return &sleep_ops;}
static typeof(n1x_sroot_client_ops_v4) *get_symbol(void)
{assert(!symbols);if(fault==1)return NULL;symbols++;return get_ops;}
static void put_symbol(void){assert(symbols==1);symbols--;}
#define symbol_get(name) get_symbol()
#define symbol_put(name) put_symbol()
static int devm_add_action_or_reset(struct device *dev,void (*fn)(void *),void *data)
{assert(dev==&device && handles==1 && symbols==1);if(fault==3){fn(data);return -ENOMEM;}
 cleanup=fn;return 0;}
''' + functions + r'''
int main(void)
{
 struct n1x_adsp dsp={.dev=&device};
 for(fault=1;fault<=3;fault++) {
  assert(n1x_adsp_get_provider(&dsp)==(fault==1?-EPROBE_DEFER:fault==2?-ENOTUNIQ:-ENOMEM));
  assert(!symbols && !handles);
 }
 fault=0;assert(!n1x_adsp_get_provider(&dsp) && symbols==1 && handles==1 && cleanup);
 cleanup(&dsp);assert(!symbols && !handles);
 assert(!n1x_adsp_get_provider(&dsp));published=true;cleanup(&dsp);
 assert(!symbols && handles==1); /* Published provider handle retains its own reference. */
 puts("DSP provider probe: absent/ambiguous suppliers, devres allocation faults, unpublished cleanup and published retention: PASS");
}
'''
    link_functions = source[source.index('static void n1x_adsp_del_link('):
                            source.index('static int n1x_adsp_link_afe(')]
    link_code = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <string.h>
#define EPROBE_DEFER 517
#define DL_FLAG_STATELESS 1
struct device {int unused;};
struct device_link {int unused;};
struct target {unsigned image_id;};
struct n1x_adsp {struct device *dev;struct target *target;};
static struct device consumer,primary;
static struct device_link link;
static unsigned fault,refs,links;
static void (*cleanup)(void *);
static struct device *n1x_adsp_find_device(struct device *dev,const char *hid)
{assert(dev==&consumer && !strcmp(hid,"NVDA8301"));if(fault==1)return NULL;refs++;return &primary;}
static struct device_link *device_link_add(struct device *a,struct device *b,unsigned flags)
{assert(a==&consumer && b==&primary && flags==DL_FLAG_STATELESS && refs==1);
 if(fault==2){return NULL;}links++;return &link;}
static void put_device(struct device *dev){assert(dev==&primary && refs==1);refs--;}
static void device_link_del(void *p){assert(p==&link && links==1);links--;}
static int devm_add_action_or_reset(struct device *dev,void (*fn)(void *),void *data)
{assert(dev==&consumer && data==&link && links==1 && !refs);
 if(fault==3){fn(data);return -ENOMEM;}cleanup=fn;return 0;}
''' + link_functions + r'''
int main(void)
{
 struct target target={0xc0304};struct n1x_adsp dsp={&consumer,&target};
 assert(!n1x_adsp_link_primary(&dsp) && !refs && !links);
 target.image_id=0xc0305;
 for(fault=1;fault<=3;fault++) {
  assert(n1x_adsp_link_primary(&dsp)==(fault==1?-EPROBE_DEFER:-ENOMEM));
  assert(!refs && !links);
 }
 fault=0;assert(!n1x_adsp_link_primary(&dsp) && !refs && links==1 && cleanup);
 cleanup(&link);assert(!links);
}
'''
    with tempfile.TemporaryDirectory(prefix='n1x-provider-') as tmp:
        test, binary = Path(tmp)/'test.c', Path(tmp)/'test'
        test.write_text(code)
        subprocess.run(['cc', '-I'+str(ROOT), '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', str(test), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
        test.write_text(link_code)
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', str(test), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
