#!/usr/bin/env python3
"""Create the AFE-owned SRAM integration patch on the pinned P16 kernel base."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / 'platform/dsp/afe'


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Expected one integration point: ' + old)
    return text.replace(old, new, 1)


def sources(base):
    pins = json.loads((CANONICAL / 'base.json').read_text())['sha256']
    before = {}
    for path, expected in pins.items():
        raw = (base / path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('Kernel base differs from pinned source: ' + path)
        before[path] = raw.decode()
    after = before.copy()
    path = 'sound/soc/mediatek/Kconfig'
    after[path] = replace_once(after[path],
                              'depends on MTK_POWER_WRAP\n\tselect SND_SOC_MEDIATEK\n',
                              'depends on MTK_POWER_WRAP\n\tselect SND_SOC_MEDIATEK\n\tselect GENERIC_ALLOCATOR\n')
    path = 'sound/soc/mediatek/mt8901/Makefile'
    after[path] = replace_once(after[path], '\tmt8901-afe-clk.o \\\n',
                              '\tmt8901-afe-clk.o \\\n\tmt8901-afe-sram.o \\\n\tmt8901-afe-dsp.o \\\n')
    path = 'sound/soc/mediatek/mt8901/mt8901-afe-common.h'
    after[path] = replace_once(after[path], 'struct mt8901_afe_private {\n',
                              'struct mt8901_afe_sram;\nstruct mt8901_afe_dsp;\n\n'
                              'struct mt8901_afe_private {\n\tstruct mt8901_afe_sram *sram;\n'
                              '\tstruct mt8901_afe_dsp *dsp;\n')
    after[path] = replace_once(after[path], 'int mt8901_afe_fs_timing(',
                              'struct platform_driver;\nextern struct platform_driver mt8901_afe_pcm_driver;\n'
                              'int mt8901_afe_sram_init(struct mtk_base_afe *afe);\n'
                              'size_t mt8901_afe_sram_size(struct mtk_base_afe *afe);\n'
                              'bool mt8901_afe_sram_busy(struct mtk_base_afe *afe);\n\n'
                              'int mt8901_afe_sram_pm_prepare(struct mtk_base_afe *afe);\n'
                              'void mt8901_afe_sram_pm_complete(struct mtk_base_afe *afe);\n'
                              'int mt8901_afe_sram_pm_save(struct mtk_base_afe *afe);\n'
                              'void mt8901_afe_sram_pm_restore(struct mtk_base_afe *afe);\n\n'
                              'int mt8901_afe_sram_domain(struct mtk_base_afe *afe, int id);\n\n'
                              'int mt8901_afe_sram_startup(struct snd_pcm_substream *substream,\n'
                              '\t\t\t    struct snd_soc_dai *dai);\n\n'
                              'int mt8901_afe_fs_timing(')
    path = 'sound/soc/mediatek/mt8901/mt8901-afe-pcm.c'
    after[path] = replace_once(after[path], '#include "mt8901-afe-clk.h"\n',
                              '#include "mt8901-afe-clk.h"\n#include "mt8901-afe-dsp.h"\n')
    after[path] = replace_once(after[path], 'static int mt8901_afe_fe_trigger(',
                              'int mt8901_afe_sram_domain(struct mtk_base_afe *afe, int id)\n'
                              '{\n'
                              '\tstruct mt8901_afe_private *priv = afe->platform_priv;\n'
                              '\tstruct mtk_dai_memif_priv *memif;\n\n'
                              '\tif (id < 0 || id >= MT8901_AFE_MEMIF_UL_START)\n'
                              '\t\treturn -EINVAL;\n'
                              '\tmemif = priv->dai_priv[id];\n'
                              '\tif (!memif)\n'
                              '\t\treturn -ENODEV;\n'
                              '\tif (memif->domain > 7)\n'
                              '\t\treturn -ERANGE;\n'
                              '\treturn memif->domain;\n'
                              '}\n\nstatic int mt8901_afe_fe_trigger(')
    after[path] = replace_once(after[path], 'ret = mtk_afe_fe_startup(substream, dai);',
                              'ret = mt8901_afe_sram_startup(substream, dai);\n'
                              '\tif (ret < 0)\n\t\treturn ret;\n'
                              '\tret = mt8901_afe_dsp_startup(substream, dai);\n'
                              '\tif (ret) {\n\t\tmtk_afe_fe_shutdown(substream, dai);\n'
                              '\t\treturn ret;\n\t}')
    after[path] = replace_once(after[path],
                              '\tunsigned int domain = memif_priv->domain;\n',
                              '\tunsigned int domain = memif_priv->domain;\n'
                              '\tint ret;\n\n'
                              '\tret = mt8901_afe_dsp_hw_params(substream);\n'
                              '\tif (ret)\n\t\treturn ret;\n')
    after[path] = replace_once(after[path], '\tswitch (cmd) {\n',
                              '\tif (mt8901_afe_dsp_active(substream))\n'
                              '\t\treturn mt8901_afe_dsp_trigger(substream, cmd);\n\n'
                              '\tswitch (cmd) {\n')
    after[path] = replace_once(after[path],
                              'static const struct snd_soc_dai_ops mt8901_afe_fe_dai_ops = {',
                              'static int mt8901_afe_fe_prepare(struct snd_pcm_substream *substream,\n'
                              '\t\t\t\t  struct snd_soc_dai *dai)\n'
                              '{\n\tint ret = mtk_afe_fe_prepare(substream, dai);\n\n'
                              '\treturn ret ? ret : mt8901_afe_dsp_prepare(substream, dai);\n}\n\n'
                              'static int mt8901_afe_fe_hw_free(struct snd_pcm_substream *substream,\n'
                              '\t\t\t\t  struct snd_soc_dai *dai)\n'
                              '{\n\tint ret = mt8901_afe_dsp_hw_free(substream, dai);\n'
                              '\tint free_ret = mtk_afe_fe_hw_free(substream, dai);\n\n'
                              '\treturn ret ? ret : free_ret;\n}\n\n'
                              'static void mt8901_afe_fe_shutdown(struct snd_pcm_substream *substream,\n'
                              '\t\t\t\t    struct snd_soc_dai *dai)\n'
                              '{\n\tmt8901_afe_dsp_shutdown(substream, dai);\n'
                              '\tmtk_afe_fe_shutdown(substream, dai);\n}\n\n'
                              'static const struct snd_soc_dai_ops mt8901_afe_fe_dai_ops = {')
    for operation in ('prepare', 'hw_free', 'shutdown'):
        after[path] = replace_once(after[path], '= mtk_afe_fe_' + operation + ',',
                                  '= mt8901_afe_fe_' + operation + ',')
    after[path] = replace_once(after[path], '\tbool skip = false;\n',
                              '\tbool skip = false;\n\n'
                              '\t/* Forced system suspend ignores the lease\'s runtime-PM vote. */\n'
                              '\tif (mt8901_afe_sram_busy(afe))\n\t\treturn -EBUSY;\n')
    after[path] = replace_once(after[path], '\tplatform_set_drvdata(pdev, afe);\n',
                              '\tplatform_set_drvdata(pdev, afe);\n\n'
                              '\tret = mt8901_afe_sram_init(afe);\n'
                              '\tif (ret)\n\t\tdev_warn(dev, "AFE SRAM unavailable: %d\\n", ret);\n')
    after[path] = replace_once(after[path],
                              '\tret = devm_snd_soc_register_component(dev, &mtk_afe_pcm_platform,',
                              '\tret = devm_snd_soc_register_component(dev, &mt8901_afe_dsp_platform,')
    after[path] = replace_once(after[path], 'static const struct dev_pm_ops mt8901_afe_pm_ops = {',
                              '#include "mt8901-afe-pm.h"\n\n'
                              'static const struct dev_pm_ops mt8901_afe_pm_ops = {\n'
                              '\t.prepare = pm_sleep_ptr(mt8901_afe_pm_prepare),\n'
                              '\t.complete = pm_sleep_ptr(mt8901_afe_pm_complete),')
    after[path] = replace_once(after[path], 'SYSTEM_SLEEP_PM_OPS(pm_runtime_force_suspend, pm_runtime_force_resume)',
                              'SYSTEM_SLEEP_PM_OPS(mt8901_afe_pm_suspend, mt8901_afe_pm_resume)')
    after[path] = replace_once(after[path], 'static struct platform_driver mt8901_afe_pcm_driver = {',
                              'struct platform_driver mt8901_afe_pcm_driver = {')
    after[path] = replace_once(after[path], '\t\t   .name = "mt8901-audio",\n',
                              '\t\t   .name = "mt8901-audio",\n'
                              '\t\t   /* SRAM consumers require stable driver ownership. */\n'
                              '\t\t   .suppress_bind_attrs = true,\n')
    after['sound/soc/mediatek/mt8901/mt8901-afe-sram.c'] = (CANONICAL / 'mt8901-afe-sram.c').read_text()
    after['include/sound/mt8901-afe-sram.h'] = (CANONICAL / 'mt8901-afe-sram.h').read_text()
    for name in ('mt8901-afe-dsp.c', 'mt8901-afe-dsp.h', 'mt8901-afe-pm.h'):
        after['sound/soc/mediatek/mt8901/' + name] = (CANONICAL / name).read_text()
    for name in ('n1x_adsp_client.h', 'n1x_adsp_pcm.h', 'n1x_adsp_ipc.h'):
        after['include/sound/' + name] = (CANONICAL.parent / name).read_text()
    path = 'sound/soc/mediatek/mt8901/mt8901-acp-sdw-legacy-mach.c'
    after[path] = replace_once(after[path], '#include <sound/soc_sdw_utils.h>\n',
                              '#include <sound/soc_sdw_utils.h>\n#include "mt8901-dsp-card.h"\n')
    after[path] = replace_once(after[path], 'static unsigned long soc_sdw_quirk;\n',
                              'static bool dsp_playback;\nmodule_param(dsp_playback, bool, 0400);\n'
                              'MODULE_PARM_DESC(dsp_playback, "Bind the firmware-backed N1X DSP audio components");\n\n'
                              'static unsigned long soc_sdw_quirk;\n')
    after[path] = replace_once(after[path], '\tcard->codec_conf = codec_conf;\n',
                              '\tcard->aux_dev = soc_aux;\n\tcard->num_aux_devs = num_aux;\n'
                              '\tcard->codec_conf = codec_conf;\n')
    after[path] = replace_once(after[path], '\tret = devm_snd_soc_register_card(card->dev, card);\n',
                              '\tret = mt8901_card_add_dsps(card, dsp_playback);\n\tif (ret)\n\t\treturn ret;\n\n'
                              '\tret = devm_snd_soc_register_card(card->dev, card);\n')
    after['sound/soc/mediatek/mt8901/mt8901-dsp-card.h'] = (CANONICAL / 'mt8901-dsp-card.h').read_text()
    return before, after


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-tree', type=Path, default=ROOT / 'kernel/src/linux-7.2.8')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists')
    before, after = sources(args.source_tree)
    patch = ('Subject: [PATCH] ASoC: mediatek: mt8901: add DSP playback and SRAM ownership\n\n'
             'Provide exclusive, aligned SRAM leases through the AFE owner on the\n'
             'firmware-described SRAM layout. Each lease retains device, module and\n'
             'runtime-PM references. Refuse forced suspend while leases exist and\n'
             'disable manual driver detachment. Published buffers remain retained\n'
             'until reboot; whole-core quiesce and release are separate work.\n\n'
             'Add an optional DL0 DSP client to the existing AFE/SoundWire route.\n'
             'Copy committed application frames into the owned DSP host ring and\n'
             'defer complete-period notifications to workqueue context. Synchronize\n'
             'listeners and drain work before retiring borrowed ALSA pointers.\n'
             'The experimental path is disabled by default and lacks hardware\n'
             'streaming qualification.\n\n---\n')
    for path in sorted(after):
        patch += ''.join(difflib.unified_diff(before.get(path, '').splitlines(True),
                                            after[path].splitlines(True),
                                            fromfile='a/' + path if path in before else '/dev/null',
                                            tofile='b/' + path))
    args.output.write_text(patch)
    print(args.output)


if __name__ == '__main__':
    main()
