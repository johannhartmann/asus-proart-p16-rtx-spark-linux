#!/usr/bin/env python3
"""Exercise the patched SSPM sender with uncertain and late completions."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PATHS = ('drivers/soc/mediatek/sspm_ci/sspm_ci.c',
         'drivers/soc/mediatek/sspm_ci/sspm_ci.h',
         'drivers/soc/mediatek/power_wrap/power_wrap.c',
         'include/linux/soc/mediatek/mtk-pwrap.h')


def main():
    with tempfile.TemporaryDirectory(prefix='n1x-dsp-power-') as directory:
        directory = Path(directory)
        for name in PATHS:
            target = directory / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / 'kernel/src/linux-7.2.8' / name).read_bytes())
        subprocess.run(['patch', '-p1', '--fuzz=0', '--batch', '-i',
                        str(ROOT / 'kernel/p16-dsp-shutdown-power.patch')],
                       cwd=directory, check=True, capture_output=True)
        source = (directory / PATHS[0]).read_text()
        sender = source[source.index('int sspm_ci_set('):
                        source.index('EXPORT_SYMBOL(sspm_ci_set);')]
        clear = source[source.index('static void sspm_ci_clear_globals('):
                       source.index('static ssize_t')]
        power = (directory / PATHS[2]).read_text()
        shutdown = power[power.index('int mtk_pwrap_dev_shutdown('):
                         power.index('EXPORT_SYMBOL_GPL(mtk_pwrap_dev_shutdown);')]
        code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <errno.h>
#include <stdio.h>
typedef uint32_t u32;
typedef uint8_t u8;
struct scmi_msg_t {u32 status,flags,length,message_header,payload[7];};
static void *sspm_mbox_iomap;
static void *__dev;
static int _hw_ack,_hw_rsc;
static u32 _inflight_hdr;
static bool _completion_unknown,_token_echo_seen;
static unsigned _stale_acks;
static u8 _scmi_token=1;
static u32 slot[32],doorbell;
static bool busy,acknowledge,locked;
static unsigned copies,writes,delays,tokens;
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
{assert(locked && ms==1);delays++;if(writes && acknowledge)_hw_ack=1;}
''' + sender + clear + r'''
static unsigned phases;
static int d3_error,abandon_error;
static int mtk_pwrap_dev_suspend(void *cfg,u8 transition)
{assert(cfg==slot && !transition && !phases);phases++;return d3_error;}
static int mtk_pwrap_dev_remove(void *cfg)
{assert(cfg==slot && phases>=1 && !d3_error);phases++;return abandon_error;}
''' + shutdown + r'''
static void fresh(void)
{
 /* Test fixture only. Production has no operation that clears this latch. */
 assert(!locked);_completion_unknown=false;sspm_mbox_iomap=slot;__dev=slot;
 _hw_ack=0;_inflight_hdr=0;_token_echo_seen=false;_stale_acks=0;_scmi_token=1;
 busy=acknowledge=false;copies=writes=delays=tokens=0;memset(slot,0,sizeof(slot));
 phases=0;d3_error=abandon_error=0;
}
static int send(void) {return sspm_ci_set(13,25,0x02040100,0,0,0);}
int main(void)
{
 fresh();sspm_mbox_iomap=NULL;assert(send()==-ENODEV && !copies && !writes);
 fresh();busy=true;assert(send()==-EBUSY && !copies && !writes && !_completion_unknown);
 busy=false;acknowledge=true;assert(!send() && copies==1 && writes==1);
 fresh();acknowledge=true;
 for(unsigned i=0;i<64;i++) assert(!send() && !_completion_unknown && !_inflight_hdr);
 assert(copies==64 && writes==64);
 fresh();assert(send()==-ETIMEDOUT && _completion_unknown && !_inflight_hdr);
 assert(copies==1 && writes==1);
 /* An arbitrarily late IRQ, including token-zero firmware, cannot make
  * another request rewrite the shared slot and steal its completion. */
 for(unsigned i=0;i<64;i++) {
  _hw_ack=1;_stale_acks++;acknowledge=true;
  unsigned old_tokens=tokens,old_delays=delays;
  assert(send()==-ENOTRECOVERABLE && copies==1 && writes==1);
  assert(tokens==old_tokens && delays==old_delays);
 }
 sspm_ci_clear_globals(NULL);assert(_completion_unknown && !sspm_mbox_iomap);
 sspm_mbox_iomap=slot;__dev=slot;
 assert(send()==-ENOTRECOVERABLE && copies==1 && writes==1);
 u32 completed=0;
 fresh();assert(!mtk_pwrap_dev_shutdown(slot,&completed) && phases==2 && completed==3);
 assert(!mtk_pwrap_dev_shutdown(slot,&completed) && phases==2);
 completed=2;fresh();assert(mtk_pwrap_dev_shutdown(slot,&completed)==-EINVAL && !phases);
 for(unsigned i=0;i<3;i++) {
  fresh();completed=0;d3_error=i==0?-EBUSY:i==1?-ETIMEDOUT:-ENOTRECOVERABLE;
  assert(mtk_pwrap_dev_shutdown(slot,&completed)==d3_error && phases==1 && !completed);
  fresh();completed=0;abandon_error=i==0?-EBUSY:i==1?-ETIMEDOUT:-ENOTRECOVERABLE;
  assert(mtk_pwrap_dev_shutdown(slot,&completed)==abandon_error && phases==2 && completed==1);
  if(i==0){abandon_error=0;assert(!mtk_pwrap_dev_shutdown(slot,&completed) && phases==3 && completed==3);}
 }
 puts("DSP power: known/unknown submission, 64 ACKs, terminal late-ACK/rebind handling, ordered D3/abandon failures: PASS");
}
'''
        harness, binary = directory / 'test.c', directory / 'test'
        harness.write_text(code)
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        '-Wno-unused-parameter', '-fsanitize=address,undefined',
                        str(harness), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
