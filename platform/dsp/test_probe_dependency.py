#!/usr/bin/env python3
"""Exercise the actual secondary DSP probe dependency before any power action."""
from pathlib import Path
import subprocess
import tempfile


def main():
    source = Path(__file__).with_name('n1x_adsp.c').read_text()
    function = source[source.index('static int n1x_adsp_link_primary('):
                      source.index('static int n1x_adsp_link_afe(')]
    code = r'''
#include <assert.h>
#include <stdbool.h>
#include <string.h>
#include <errno.h>
#include <stdio.h>
#define EPROBE_DEFER 517
#define READ_ONCE(x) (x)
#define DL_FLAG_STATELESS 1
struct device_driver {const char *name;};
struct device {struct device_driver *driver;void *data;int refs;};
struct device_link {int unused;};
struct n1x_adsp_target {unsigned image_id;};
struct n1x_adsp {struct device *dev;const struct n1x_adsp_target *target;
 bool boot_ready,component_registered;};
static bool auto_boot=true,missing,fail_link;
static unsigned locks,links,actions;
static struct device primary,consumer;
static struct device_link link;
static struct device *n1x_adsp_find_device(struct device *d,const char *hid)
{assert(d==&consumer && !strcmp(hid,"NVDA8301"));if(missing)return NULL;
 primary.refs++;return &primary;}
static void put_device(struct device *d){assert(d==&primary && --d->refs==1);}
static void device_lock(struct device *d){assert(d==&primary && !locks++);}
static void device_unlock(struct device *d){assert(d==&primary && locks--==1);}
static void *dev_get_drvdata(struct device *d){assert(d==&primary && locks==1);return d->data;}
static struct device_link *device_link_add(struct device *d,struct device *p,int flags)
{assert(d==&consumer && p==&primary && !locks && flags==1);links++;return fail_link?NULL:&link;}
static void n1x_adsp_del_link(void *data){assert(data==&link);}
static int devm_add_action_or_reset(struct device *d,void (*action)(void *),void *data)
{assert(d==&consumer && action==n1x_adsp_del_link && data==&link);actions++;return 0;}
''' + function + r'''
int main(void)
{
 struct device_driver driver={"n1x-adsp"},other={"other"};
 struct n1x_adsp_target target={0xc0305};
 struct n1x_adsp first={0},dsp={.dev=&consumer,.target=&target};
 primary.refs=1;missing=true;
 assert(n1x_adsp_link_primary(&dsp)==-EPROBE_DEFER && !links);
 missing=false;
 assert(n1x_adsp_link_primary(&dsp)==-EPROBE_DEFER && !links);
 primary.driver=&other;primary.data=&first;
 assert(n1x_adsp_link_primary(&dsp)==-EPROBE_DEFER && !links);
 primary.driver=&driver;
 assert(n1x_adsp_link_primary(&dsp)==-EPROBE_DEFER && !links);
 first.boot_ready=true;
 assert(n1x_adsp_link_primary(&dsp)==-EPROBE_DEFER && !links);
 first.component_registered=true;fail_link=true;
 assert(n1x_adsp_link_primary(&dsp)==-ENOMEM && links==1 && !actions);
 fail_link=false;
 assert(!n1x_adsp_link_primary(&dsp) && links==2 && actions==1);
 auto_boot=false;first.boot_ready=false;
 assert(!n1x_adsp_link_primary(&dsp) && actions==2);
 target.image_id=0xc0304;missing=true;
 assert(!n1x_adsp_link_primary(&dsp) && actions==2);
 assert(primary.refs==1 && !locks);
 puts("DSP coldplug: deferred primary readiness, reference balance and explicit-mode compatibility: PASS");
}
'''
    with tempfile.TemporaryDirectory(prefix='n1x-probe-dependency-') as temporary:
        code_path, binary = Path(temporary)/'test.c', Path(temporary)/'test'
        code_path.write_text(code)
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', str(code_path), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
