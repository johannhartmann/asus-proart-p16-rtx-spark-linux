// SPDX-License-Identifier: GPL-2.0-only
/* Temporary migration for the qualified kernel31 / AFE 0.1.27 instance.
 * The permanent fix lives in p16-afe-const-irq-shutdown.patch.
 */
#include <linux/module.h>
#include <linux/livepatch.h>
#include <linux/dmi.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>
#include <linux/utsname.h>
#include <sound/soc.h>
#include <sound/mt8901-afe-sram.h>
#include "mtk-base-afe.h"
#include "mtk-afe-fe-dai.h"
#include "mt8901-afe-common.h"

/* Exact private layout from AFE 0.1.27, guarded by the loaded source revision. */
struct mt8901_afe_sram {
	struct gen_pool *pool;
	void __iomem *base;
	u32 cpu, vad, dsp, bytes;
	atomic_t users, retention_users, sleeping_users;
	void *snapshot;
	bool sleep_prepared, sleep_saved;
	struct mt8901_afe_sram_buffer *memif[MT8901_AFE_MEMIF_NUM];
};
struct mt8901_afe_sram_buffer {
	struct device *dev;
	struct mt8901_afe_sram *sram;
	unsigned long address;
	size_t bytes;
	bool published, ipc, retention, asleep, prepared, irq_prepared, irq_stopped;
	int prepare_error, irq_error, irq_stop_error;
	bool started;
	int start_error;
	struct snd_pcm_substream *substream;
	struct mt8901_afe_sram_endpoint endpoint;
};

static void fixed_shutdown(struct snd_pcm_substream *substream, struct snd_soc_dai *dai)
{
	struct snd_soc_pcm_runtime *rtd = snd_soc_substream_to_rtd(substream);
	struct mtk_base_afe *afe = snd_soc_dai_get_drvdata(dai);
	struct mtk_base_afe_memif *memif = &afe->memif[snd_soc_rtd_to_cpu(rtd, 0)->id];
	int reg = memif->data->agent_disable_reg;
	int shift = memif->data->agent_disable_shift;

	if (reg >= 0 && !WARN_ON_ONCE(shift < 0))
		regmap_update_bits(afe->regmap, reg, 1U << shift, 1U << shift);
	if (!memif->const_irq) {
		mtk_dynamic_irq_release(afe, memif->irq_usage);
		memif->irq_usage = -1;
	}
	memif->substream = NULL;
}

static int migrate_closed_borrowers(struct klp_object *obj)
{
	struct device *card, *dev;
	struct mtk_base_afe *afe;
	struct mt8901_afe_private *priv;
	int i, ret = 0, cleared = 0;

	card = bus_find_device_by_name(&platform_bus_type, NULL, "mtk_sdw_mc");
	dev = bus_find_device_by_name(&platform_bus_type, NULL, "NVDA9022:00");
	/* A later common-module reload precedes AFE/card probe. */
	if (!dev || !dev->driver)
		goto put;
	if (!card || !device_trylock(card)) {
		ret = -EBUSY;
		goto put;
	}
	if (card->driver || !device_trylock(dev)) {
		ret = -EBUSY;
		goto card_unlock;
	}
	if (!dev->driver->owner || strcmp(dev->driver->owner->name, "snd_soc_mt8901_afe") ||
	    !dev->driver->owner->version || strcmp(dev->driver->owner->version, "0.1.27") ||
	    !dev->driver->owner->srcversion ||
	    strcmp(dev->driver->owner->srcversion, EXPECTED_AFE_SRCVERSION)) {
		ret = -ESTALE;
		goto unlock;
	}
	afe = dev_get_drvdata(dev);
	priv = afe->platform_priv;
	if (!priv->sram || priv->sram->sleep_prepared || priv->sram->sleep_saved) {
		ret = -EBUSY;
		goto unlock;
	}
	for (i = 0; i < afe->memif_size && i < MT8901_AFE_MEMIF_NUM; i++) {
		struct mt8901_afe_sram_buffer *buffer = priv->sram->memif[i];

		/* The detached card cannot create new clients. Only clear a borrower
		 * already retired by its published SRAM owner; no DMA or IRQ changes.
		 */
		if (!buffer || buffer->dev != dev || buffer->sram != priv->sram ||
		    !buffer->published || buffer->ipc || buffer->substream || buffer->asleep ||
		    buffer->endpoint.memif != i || !afe->memif[i].const_irq)
			continue;
		if (afe->memif[i].substream) {
			afe->memif[i].substream = NULL;
			cleared++;
		}
	}
	pr_info("n1x AFE: retired %d closed fixed-IRQ borrower pointers\n", cleared);
unlock:
	device_unlock(dev);
card_unlock:
	device_unlock(card);
put:
	put_device(dev);
	put_device(card);
	return ret;
}

static struct klp_func funcs[] = {
	{ .old_name = "mtk_afe_fe_shutdown", .new_func = fixed_shutdown }, { }
};
static struct klp_object objects[] = {
	{ .name = "snd_soc_mtk_common", .funcs = funcs,
	  .callbacks.pre_patch = migrate_closed_borrowers }, { }
};
static struct klp_patch patch = { .mod = THIS_MODULE, .objs = objects };
static int __init fix_init(void)
{
	if (strcmp(utsname()->release, "7.2.8-31-rtx-spark-npu") ||
	    !dmi_match(DMI_BOARD_NAME, "H7607BA"))
		return -ENODEV;
	return klp_enable_patch(&patch);
}
static void __exit fix_exit(void) { }
module_init(fix_init);
module_exit(fix_exit);
MODULE_INFO(livepatch, "Y");
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Kernel31 MT8901 fixed-IRQ PCM borrower lifetime migration");
