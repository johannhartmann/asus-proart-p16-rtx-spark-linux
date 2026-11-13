#!/usr/bin/env python3
"""Exercise the actual generic AFE close function with fixed and dynamic IRQs."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]
NAME = 'sound/soc/mediatek/common/mtk-afe-fe-dai.c'
PRELUDE = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
struct snd_pcm_substream {int dummy;};
struct snd_soc_dai {int id;};
struct snd_soc_pcm_runtime {struct snd_soc_dai *cpu;};
struct data {int agent_disable_reg,agent_disable_shift;};
struct mtk_base_afe_memif {const struct data *data;int irq_usage;bool const_irq;struct snd_pcm_substream *substream;};
struct mtk_base_afe {struct mtk_base_afe_memif *memif;void *regmap;};
static struct snd_soc_pcm_runtime rtd;
static struct mtk_base_afe afe;
static int releases,writes;
static struct snd_soc_pcm_runtime *snd_soc_substream_to_rtd(struct snd_pcm_substream *s)
{(void)s;return &rtd;}
static struct snd_soc_dai *snd_soc_rtd_to_cpu(struct snd_soc_pcm_runtime *r,int i)
{assert(!i);return r->cpu;}
static struct mtk_base_afe *snd_soc_dai_get_drvdata(struct snd_soc_dai *d)
{(void)d;return &afe;}
static void mtk_regmap_update_bits(void *map,int reg,int mask,int value,int shift)
{(void)map;assert(reg==4 && mask==1 && value==1 && shift==6);writes++;}
static void mtk_dynamic_irq_release(struct mtk_base_afe *a,int irq)
{assert(a==&afe && irq==7);releases++;}
'''
MAIN = r'''
int main(void) {
 struct snd_pcm_substream stream={0};struct snd_soc_dai dai={0};
 const struct data data={4,6};struct mtk_base_afe_memif memif={.data=&data};
 rtd.cpu=&dai;afe.memif=&memif;
 for(unsigned fixed=0;fixed<2;fixed++) {
  memif.irq_usage=7;memif.const_irq=fixed;memif.substream=&stream;
  releases=writes=0;mtk_afe_fe_shutdown(&stream,&dai);
  assert(writes==1 && releases==(fixed?0:1));
  assert(memif.irq_usage==(fixed?7:-1));
  if(memif.substream)return 42;
 }
 return 0;
}
'''

def function(text):
    return text[text.index('void mtk_afe_fe_shutdown('):text.index('EXPORT_SYMBOL_GPL(mtk_afe_fe_shutdown);')]


def main():
    with tempfile.TemporaryDirectory(prefix='afe-irq-close-') as tmp:
        tmp=Path(tmp);p=tmp/NAME;p.parent.mkdir(parents=True)
        # The patch retains the complete upstream function as context, so CI
        # exercises the actual old/new functions without downloading a kernel.
        patch=(ROOT/'kernel/p16-afe-const-irq-shutdown.patch').read_text()
        hunk=patch.split('@@',2)[2].splitlines()[1:]
        original=''.join(line[1:]+'\n' for line in hunk if line.startswith((' ', '-')))
        p.write_text(original)
        subprocess.run(['patch','-p1','--fuzz=0','--batch','-i',str(ROOT/'kernel/p16-afe-const-irq-shutdown.patch')],cwd=tmp,check=True,capture_output=True)
        for label,source,expected in [('old',original,42),('fixed',p.read_text(),0)]:
            code=tmp/(label+'.c');binary=tmp/label;code.write_text(PRELUDE+function(source)+MAIN)
            subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(code),'-o',str(binary)],check=True)
            result=subprocess.run([str(binary)])
            assert result.returncode==expected,(label,result.returncode)
    print('AFE close: old fixed-IRQ stale borrower reproduced; fixed/dynamic close and IRQ reservation: PASS')

if __name__=='__main__':main()
