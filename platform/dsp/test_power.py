#!/usr/bin/env python3
"""Check normal SSPM against the booted baseline and checked DSP retirement."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PATHS = ('drivers/soc/mediatek/sspm_ci/sspm_ci.c',
         'drivers/soc/mediatek/sspm_ci/sspm_ci.h',
         'drivers/soc/mediatek/power_wrap/power_wrap.c',
         'include/linux/soc/mediatek/mtk-pwrap.h',
         'drivers/soc/mediatek/power_wrap/inc/pwrap_scmi.h')
PRELUDE = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <errno.h>
#include <stdio.h>
typedef uint32_t u32;typedef uint8_t u8;
struct scmi_msg_t {u32 status,flags,length,message_header,payload[7];};
static void *sspm_mbox_iomap,*__dev;
static int _hw_ack,_hw_rsc;
static u32 _inflight_hdr;
static bool _completion_unknown,_token_echo_seen,_drain_needed;
static unsigned _stale_acks;
static u8 _scmi_token=1;
static u32 slot[32],doorbell;
static bool busy,acknowledge,locked;
static unsigned copies,writes,delays,tokens;
#define SSPM_CI_DRAIN_MS 100
#define SSPM_CI_MAX_POLL_COUNT 3
#define SSPM_CI_SET_ID 0
#define SSPM_CI_MAGIC 0xabcdef
#define TINYSYS_COMMON_SET 3
#define SCMI_PROTOCOL_TINYSYS 0x80
#define SCMI_MESSAGE_TYPE_COMMAND 0
struct scmi_tinysys_common_set_state {u32 words[7];};
#define MBOX_IN_SET(id) (&doorbell)
#define MBOX_BOX(id,offset) ((void *)slot)
#define __iomem
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define dev_err(...) ((void)0)
#define dev_dbg(...) ((void)0)
#define EXPORT_SYMBOL(...)
#define EXPORT_SYMBOL_GPL(...)
static void mutex_lock(int *m) {assert(m==&_hw_rsc && !locked);locked=true;}
static void mutex_unlock(int *m) {assert(m==&_hw_rsc && locked);locked=false;}
static u8 sspm_ci_next_token(void) {tokens++;return _scmi_token++;}
static u32 pack_message_header(u8 msg,u8 type,u8 proto,u8 token)
{assert(msg==3 && !type && proto==0x80);return msg|(u32)proto<<10|(u32)token<<18;}
static u32 readl(const void *p) {assert(locked && p==&doorbell);return busy;}
static void memcpy_toio(void *p,const void *from,size_t bytes)
{assert(locked && p==slot && bytes==sizeof(struct scmi_msg_t));copies++;memcpy(p,from,bytes);}
static void writel(u32 value,void *p)
{assert(locked && p==&doorbell && value==SSPM_CI_MAGIC && _inflight_hdr);writes++;}
static void mdelay(unsigned ms)
{assert(locked && ms==1);delays++;if(writes && acknowledge){if(_inflight_hdr)_hw_ack=1;else _stale_acks++;}}
'''
FRESH = r'''
static void fresh(void)
{
 /* Fixture only: production never clears the unknown-completion history. */
 assert(!locked);_completion_unknown=false;sspm_mbox_iomap=slot;__dev=slot;
 _hw_ack=0;_inflight_hdr=0;_token_echo_seen=false;_stale_acks=0;_scmi_token=1;_drain_needed=false;
 busy=acknowledge=false;copies=writes=delays=tokens=0;memset(slot,0,sizeof(slot));
}
static int send(void) {return sspm_ci_set(13,25,0x02040100,0,0,0);}
'''
NORMAL = r'''
static void trace(int ret)
{printf("%d %u %u %u %u %#x %#x\n",ret,copies,writes,delays,tokens,slot[3],slot[6]);}
int main(void)
{
 fresh();sspm_mbox_iomap=NULL;trace(send());
 fresh();busy=true;trace(send());busy=false;acknowledge=true;trace(send());
 fresh();acknowledge=true;for(unsigned i=0;i<64;i++)trace(send());
 fresh();trace(send());acknowledge=true;trace(send());
 sspm_ci_clear_globals(NULL);sspm_mbox_iomap=slot;__dev=slot;trace(send());
 fresh();trace(send());trace(send());acknowledge=true;trace(send());
}
'''
CHECKED = r'''
static int checked(void) {return sspm_ci_set_checked(13,25,0x02040100,0,0,0);}
static void transport_tests(void)
{
 fresh();sspm_mbox_iomap=NULL;assert(checked()==-ENODEV && !copies);
 fresh();busy=true;assert(checked()==-EBUSY && !copies && !_completion_unknown);
 busy=false;acknowledge=true;assert(!checked() && writes==1);
 fresh();acknowledge=true;for(unsigned i=0;i<64;i++)assert(!checked() && !_completion_unknown);
 fresh();assert(checked()==-ETIMEDOUT && _completion_unknown && writes==1);
 for(unsigned i=0;i<64;i++) {
  _hw_ack=1;_stale_acks++;acknowledge=true;unsigned old_tokens=tokens,old_delays=delays;
  assert(checked()==-ENOTRECOVERABLE && writes==1 && tokens==old_tokens && delays==old_delays);
 }
 /* A normal client may recover, but its successful ACK cannot authorize
  * checked retirement after an earlier ambiguous transaction. */
 assert(!send() && writes==2 && _completion_unknown);
 assert(checked()==-ENOTRECOVERABLE && writes==2);
 sspm_ci_clear_globals(NULL);sspm_mbox_iomap=slot;__dev=slot;
 assert(checked()==-ENOTRECOVERABLE && writes==2);
 /* Ambiguity from a normal boot/power caller also disqualifies shutdown. */
 fresh();assert(send()==-ETIMEDOUT && _completion_unknown);
 acknowledge=true;assert(checked()==-ENOTRECOVERABLE && writes==1);
 assert(!send() && writes==2);assert(checked()==-ENOTRECOVERABLE && writes==2);
}
struct pwrap_scmi_config {u32 feat_id,dev_id,data[5][4];};
struct pwrap_dev_config {unsigned control_type;const char *device_path;struct pwrap_scmi_config scmi_config;};
#define CTRL_BY_SCMI 2
#define SCMI_DEV_STATE 1
#define SCMI_DEV_ADANDON 4
#define SCMI_DATA_00 0
#define SCMI_DATA_01 1
#define SCMI_DATA_02 2
#define SCMI_DATA_03 3
#define DEV_STA_D3 4
#define PWRAP_SCMI_DEV_ACT_PAYLOAD(a,s,c,t) (((a)&0xff000000U)|((u32)(s)<<16)|((u32)(c)<<8)|(t))
#define pr_warn(...) ((void)0)
#define pr_debug(...) ((void)0)
static unsigned phases,normal_calls;
static int d3_error,abandon_error;
static int checked_power(u32 feature,u32 dev,u32 action,u32 p3,u32 p4,u32 p5)
{
 assert(feature==13 && dev==25 && !p3 && !p4 && !p5);
 if(action==0x02040100){assert(!phases);phases++;return d3_error;}
 assert(action==0x05000000 && phases>=1 && !d3_error);phases++;return abandon_error;
}
static int normal_power(u32 feature,u32 dev,u32 action,u32 p3,u32 p4,u32 p5)
{assert(feature==13 && dev==25 && !p3 && !p4 && !p5);
 assert(action==0x02040100 || action==0x05000000);normal_calls++;return 0;}
#define sspm_ci_set normal_power
#define sspm_ci_set_checked checked_power
'''
POWER_MAIN = r'''
int main(void)
{
 transport_tests();
 struct pwrap_dev_config cfg={.control_type=2,.device_path="DSP1",
  .scmi_config={.feat_id=13,.dev_id=25,.data={[1]={0x02000000},[4]={0x05000000}}}};
 u32 completed=0;assert(!mtk_pwrap_dev_shutdown(&cfg,&completed) && phases==2 && completed==3 && !normal_calls);
 assert(!mtk_pwrap_dev_shutdown(&cfg,&completed) && phases==2);
 completed=2;phases=0;assert(mtk_pwrap_dev_shutdown(&cfg,&completed)==-EINVAL && !phases);
 for(unsigned i=0;i<3;i++) {
  phases=0;completed=0;d3_error=i==0?-EBUSY:i==1?-ETIMEDOUT:-ENOTRECOVERABLE;
  assert(mtk_pwrap_dev_shutdown(&cfg,&completed)==d3_error && phases==1 && !completed);
  phases=0;d3_error=0;completed=0;abandon_error=i==0?-EBUSY:i==1?-ETIMEDOUT:-ENOTRECOVERABLE;
  assert(mtk_pwrap_dev_shutdown(&cfg,&completed)==abandon_error && phases==2 && completed==1);
  if(i==0){abandon_error=0;assert(!mtk_pwrap_dev_shutdown(&cfg,&completed) && phases==3 && completed==3);}
 }
 /* The ordinary native calls still select the normal transport, with
  * exactly the same D3/abandon payloads as the checked lifetime operation. */
 assert(!mtk_pwrap_dev_suspend(&cfg,0) && !mtk_pwrap_dev_remove(&cfg) && normal_calls==2);
 puts("SSPM normal trace matches baseline; checked timeouts/rebind/legacy recovery stay terminal; native checked D3/abandon wire and stage masks: PASS");
}
'''


def extract(source, checked):
    clear = source[source.index('static void sspm_ci_clear_globals('):source.index('static ssize_t')]
    start = source.index('static int sspm_ci_set_mode(' if checked else 'int sspm_ci_set(')
    stop = 'EXPORT_SYMBOL_GPL(sspm_ci_set_checked);' if checked else 'EXPORT_SYMBOL(sspm_ci_set);'
    sender = source[start:source.index(stop)+len(stop)]
    return PRELUDE+clear+sender+FRESH


def compile_run(directory, name, code):
    source,binary = directory/(name+'.c'),directory/name
    source.write_text(code)
    subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-parameter',
                    '-fsanitize=address,undefined',str(source),'-o',str(binary)],check=True)
    return subprocess.check_output([str(binary)],text=True)


def main():
    baseline = (ROOT/'kernel/src/linux-7.2.8'/PATHS[0]).read_text()
    with tempfile.TemporaryDirectory(prefix='n1x-dsp-power-') as temporary:
        directory = Path(temporary)
        for name in PATHS:
            target=directory/name;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes((ROOT/'kernel/src/linux-7.2.8'/name).read_bytes())
        subprocess.run(['patch','-p1','--fuzz=0','--batch','-i',str(ROOT/'kernel/p16-dsp-shutdown-power.patch')],
                       cwd=directory,check=True,capture_output=True)
        source=(directory/PATHS[0]).read_text()
        before=compile_run(directory,'baseline',extract(baseline,False)+NORMAL)
        after=compile_run(directory,'normal',extract(source,True)+NORMAL)
        assert before==after, 'Normal boot/power wire/timeout/recovery behavior differs from baseline'
        power=(directory/PATHS[2]).read_text()
        dispatch=power[power.index('static int pwrap_scmi_dispatch('):power.index('int mtk_pwrap_dev_request(')]
        shutdown=power[power.index('int mtk_pwrap_dev_shutdown('):power.index('EXPORT_SYMBOL_GPL(mtk_pwrap_dev_shutdown);')]
        suspend=power[power.index('int mtk_pwrap_dev_suspend('):power.index('EXPORT_SYMBOL_GPL(mtk_pwrap_dev_suspend);')]
        remove=power[power.index('int mtk_pwrap_dev_remove('):power.index('EXPORT_SYMBOL_GPL(mtk_pwrap_dev_remove);')]
        print(compile_run(directory,'checked',extract(source,True)+CHECKED+dispatch+shutdown+suspend+remove+POWER_MAIN),end='')


if __name__ == '__main__':
    main()
