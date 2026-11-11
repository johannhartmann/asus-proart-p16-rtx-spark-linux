#!/usr/bin/env python3
"""Exercise actual native IRQ callbacks against divergent cache/hardware state."""
from pathlib import Path
import re
import subprocess
import tempfile
from test_sram import patched_pcm

ROOT = Path(__file__).resolve().parents[3]


def main():
    pcm = patched_pcm()
    def function(name):
        start = pcm.index(name + '(')
        start = pcm.rfind('\nstatic ', 0, start) + 1
        return pcm[start:pcm.index('\n}\n', start) + 3]
    funcs = '\n'.join(function(name) for name in ('mt8901_is_volatile_reg',
                    'mt8901_afe_irq_clear', 'mt8901_afe_irq_enable',
                    'mt8901_afe_irq_disable', 'mt8901_afe_irq_configure'))
    path = 'sound/soc/mediatek/mt8901/mt8901-reg.h'
    sections = re.split(r'(?=^diff --git )', (ROOT/'kernel/1030-n1x-audio.patch').read_text(), flags=re.M)
    header_patch = ''.join(s for s in sections if s.startswith(f'diff --git a/{path} b/{path}\n'))
    code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "sound/soc/mediatek/mt8901/mt8901-reg.h"
#define BIT(n) (1U<<(n))
struct device;
struct mtk_base_irq_data {
 int irq_cnt_reg,irq_cnt_shift,irq_cnt_maskbit;
 int irq_fs_reg,irq_fs_shift,irq_fs_maskbit;
 int irq_domain_reg,irq_domain_shift,irq_domain_maskbit;
 int irq_en_reg,irq_en_shift,irq_clr_reg,irq_clr_shift,irq_mask_reg,irq_mask_shift;
};
struct mtk_base_afe_memif {int irq_usage;};
struct mtk_base_afe_irq {const struct mtk_base_irq_data *irq_data;};
struct mtk_base_afe {void *regmap;struct mtk_base_afe_memif memif[2];struct mtk_base_afe_irq irqs[8];};
static bool mt8901_is_volatile_reg(struct device *dev,unsigned reg);
static uint32_t cache[AFE_MAX_REGISTER/4+1],hardware[AFE_MAX_REGISTER/4+1];
static unsigned writes;
static int regmap_read(void *map,unsigned reg,unsigned *value) {
 assert(map==cache && !(reg%4) && reg<=AFE_MAX_REGISTER);
 *value=mt8901_is_volatile_reg(NULL,reg)?hardware[reg/4]:cache[reg/4];return 0;
}
static int regmap_update_bits(void *map,unsigned reg,unsigned mask,unsigned value) {
 unsigned old;regmap_read(map,reg,&old);unsigned next=(old&~mask)|(value&mask);
 if(next!=old){hardware[reg/4]=next;writes++;}
 if(!mt8901_is_volatile_reg(NULL,reg))cache[reg/4]=next;
 return 0;
}
static int regmap_set_bits(void *map,unsigned reg,unsigned mask) {return regmap_update_bits(map,reg,mask,mask);}
static int regmap_clear_bits(void *map,unsigned reg,unsigned mask) {return regmap_update_bits(map,reg,mask,0);}
''' + funcs + r'''
int main(void) {
 struct mtk_base_afe afe={.regmap=cache};
 for(unsigned reg=AFE_IRQ0_MCU_CFG0;reg<=AFE_IRQ21_MCU_CFG1;reg+=4)
  assert(mt8901_is_volatile_reg(NULL,reg));
 assert(mt8901_is_volatile_reg(NULL,AFE_IRQ_MCU_EN));
 assert(mt8901_is_volatile_reg(NULL,AFE_IRQ_MCU_DSP_EN));
 assert(mt8901_is_volatile_reg(NULL,AFE_IRQ_MCU_DSP2_EN));
 assert(mt8901_is_volatile_reg(NULL,AFE_IRQ_MCU_SCP_EN));
 assert(mt8901_is_volatile_reg(NULL,AFE_IRQ_MCU_DSP3_EN));
 assert(!mt8901_is_volatile_reg(NULL,AFE_DL0_CON0)); /* Format still restored by regcache. */
 for(unsigned id=0;id<2;id++) {
  unsigned irq=id?7:0,cfg=AFE_IRQ0_MCU_CFG0+irq*8;
  struct mtk_base_irq_data data={.irq_cnt_reg=cfg+4,.irq_cnt_maskbit=0xffffff,
   .irq_fs_reg=cfg,.irq_fs_shift=4,.irq_fs_maskbit=0x1f,
   .irq_domain_reg=cfg,.irq_domain_shift=9,.irq_domain_maskbit=7,
   .irq_en_reg=cfg,.irq_clr_reg=cfg+4,.irq_clr_shift=31,
   .irq_mask_reg=AFE_IRQ_MCU_EN,.irq_mask_shift=irq};
  afe.memif[id].irq_usage=irq;afe.irqs[irq].irq_data=&data;
  for(unsigned cycle=0;cycle<32;cycle++) {
   memset(cache,0xff,sizeof(cache));memset(hardware,0,sizeof(hardware));writes=0;
   hardware[(cfg+4)/4]=1024; /* Stale cached ACK=1, actual ACK=0. */
   mt8901_afe_irq_clear(&afe,&data);
   assert(hardware[(cfg+4)/4]==(1024|BIT(31)) && writes==1);
   hardware[AFE_IRQ_MCU_EN/4]=BIT(5);
   mt8901_afe_irq_configure(&afe,id,10,1,1024);mt8901_afe_irq_enable(&afe,&data);
   assert(hardware[cfg/4]==0x2a1 && hardware[AFE_IRQ_MCU_EN/4]==(BIT(5)|BIT(irq)));
   mt8901_afe_irq_disable(&afe,&data);
   assert(hardware[cfg/4]==0x2a0 && hardware[(cfg+4)/4]==1024);
   assert(hardware[AFE_IRQ_MCU_EN/4]==BIT(5));
   /* Power loss changes hardware only. A subsequent native START reconfigures. */
   memset(hardware,0,sizeof(hardware));
   mt8901_afe_irq_configure(&afe,id,10,1,1024);mt8901_afe_irq_enable(&afe,&data);
   assert(hardware[cfg/4]==0x2a1 && hardware[(cfg+4)/4]==1024);
   assert(hardware[AFE_IRQ_MCU_EN/4]==BIT(irq));
  }
 }
 puts("AFE IRQ cache: actual volatile policy, fresh ACK/RMW, unrelated bits and 32 playback/capture power-loss cycles: PASS");
}
'''
    with tempfile.TemporaryDirectory(prefix='afe-irq-cache-') as directory:
        root = Path(directory)
        subprocess.run(['patch', '--batch', '--fuzz=0', '-p1'], input=header_patch,
                       cwd=root, text=True, check=True, stdout=subprocess.PIPE)
        source, binary = root/'test.c', root/'test'
        source.write_text(code)
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                        '-fsanitize=address,undefined', str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
