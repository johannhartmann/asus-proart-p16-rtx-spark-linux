// SPDX-License-Identifier: GPL-2.0-only
#include <linux/dma-mapping.h>
#include <linux/err.h>
#include <linux/interrupt.h>
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/slab.h>
#include <linux/spinlock.h>
#include <linux/workqueue.h>
#include <sound/mt8901-afe-sram.h>
#include <sound/n1x_adsp_client.h>
#include <sound/soc.h>

#include "mt8901-afe-common.h"
#include "mt8901-afe-dsp.h"
#include "../common/mtk-afe-platform-driver.h"

/* The processing task also needs two independently retained 1 KiB IPC slices. */
#define MT8901_DSP_IPC_BYTES 2048U

MODULE_VERSION("0.1.27");

static bool dsp_capture;
module_param(dsp_capture, bool, 0400);
MODULE_PARM_DESC(dsp_capture, "Use firmware-backed HiFi5 capture on UL1; disabled by default");

static bool dsp_playback;
module_param(dsp_playback, bool, 0400);
MODULE_PARM_DESC(dsp_playback, "Use firmware-backed HiFi1 playback on DL0/DL1; disabled by default");

bool mt8901_afe_dsp_enabled(void)
{
	return dsp_playback || dsp_capture;
}

struct mt8901_afe_dsp {
	struct snd_pcm_substream *substream;
	struct n1x_adsp_primary *primary;
	struct n1x_adsp_primary_pcm_view view;
	struct work_struct period_work;
	spinlock_t period_lock;
	u32 irq_offset, period_bytes, period_remainder;
	bool period_pending;
	int notification_error;
	snd_pcm_uframes_t appl_ptr;
	bool configured, prepared, listening, closing, running, samples, capture;
	u32 capture_pending_bytes, capture_offset;
	int error;
	typeof(n1x_adsp_primary_abi) *abi;
	typeof(n1x_adsp_primary_open_pcm) *open;
	typeof(n1x_adsp_primary_rebind) *rebind;
	typeof(n1x_adsp_primary_configure) *configure;
	typeof(n1x_adsp_primary_prepare_pcm) *prepare;
	typeof(n1x_adsp_primary_pcm_view) *pcm_view;
	typeof(n1x_adsp_primary_commit) *commit;
	typeof(n1x_adsp_primary_start) *start;
	typeof(n1x_adsp_primary_stop) *stop;
	typeof(n1x_adsp_primary_set_period) *set_period;
	typeof(n1x_adsp_primary_position) *position;
	typeof(n1x_adsp_primary_close) *close;
};

static struct mt8901_afe_dsp *mt8901_afe_dsp_get(struct snd_pcm_substream *substream)
{
	struct snd_soc_pcm_runtime *rtd = snd_soc_substream_to_rtd(substream);
	struct snd_soc_dai *dai = snd_soc_rtd_to_cpu(rtd, 0);
	struct mtk_base_afe *afe = snd_soc_dai_get_drvdata(dai);
	struct mt8901_afe_private *priv = afe->platform_priv;
	struct mt8901_afe_dsp *dsp = priv->dsp[substream->stream];

	return dsp && dsp->substream == substream ? dsp : NULL;
}

bool mt8901_afe_dsp_active(struct snd_pcm_substream *substream)
{
	return !!mt8901_afe_dsp_get(substream);
}

static void mt8901_afe_dsp_put_ops(struct mt8901_afe_dsp *dsp)
{
	if (dsp->abi)
		symbol_put(n1x_adsp_primary_abi);
	if (dsp->open)
		symbol_put(n1x_adsp_primary_open_pcm);
	if (dsp->rebind)
		symbol_put(n1x_adsp_primary_rebind);
	if (dsp->configure)
		symbol_put(n1x_adsp_primary_configure);
	if (dsp->prepare)
		symbol_put(n1x_adsp_primary_prepare_pcm);
	if (dsp->pcm_view)
		symbol_put(n1x_adsp_primary_pcm_view);
	if (dsp->commit)
		symbol_put(n1x_adsp_primary_commit);
	if (dsp->start)
		symbol_put(n1x_adsp_primary_start);
	if (dsp->stop)
		symbol_put(n1x_adsp_primary_stop);
	if (dsp->set_period)
		symbol_put(n1x_adsp_primary_set_period);
	if (dsp->position)
		symbol_put(n1x_adsp_primary_position);
	if (dsp->close)
		symbol_put(n1x_adsp_primary_close);
}

/* Copy only firmware-produced capture bytes. Keep in-flight bytes counted
 * until copying completes, so IRQ overrun detection also covers this window.
 * The ALSA pointer is published after the DMA read and CPU copy, never before.
 */
static void mt8901_afe_dsp_capture_work(struct mt8901_afe_dsp *dsp)
{
	struct snd_pcm_runtime *runtime = dsp->substream->runtime;
	unsigned long flags;
	u32 bytes, offset, first;
	bool elapsed;
	int error;

	for (;;) {
		spin_lock_irqsave(&dsp->period_lock, flags);
		bytes = dsp->capture_pending_bytes;
		offset = dsp->capture_offset;
		error = dsp->notification_error;
		spin_unlock_irqrestore(&dsp->period_lock, flags);
		if (READ_ONCE(dsp->closing) || !READ_ONCE(dsp->running))
			return;
		if (error) {
			snd_pcm_stop_xrun(dsp->substream);
			return;
		}
		if (!bytes)
			return;
		first = min_t(u32, bytes, dsp->view.bytes - offset);
		/* Firmware samples precede its producer notification. */
		dma_rmb();
		memcpy(runtime->dma_area + offset, dsp->view.area + offset, first);
		if (bytes > first)
			memcpy(runtime->dma_area, dsp->view.area, bytes - first);
		spin_lock_irqsave(&dsp->period_lock, flags);
		error = dsp->notification_error;
		if (!error) {
			dsp->capture_pending_bytes -= bytes;
			dsp->period_remainder += bytes;
			elapsed = dsp->period_remainder >= dsp->period_bytes;
			dsp->period_remainder %= dsp->period_bytes;
			/* The stream lock cannot be acquired from the IRQ path. */
			smp_store_release(&dsp->capture_offset, (offset + bytes) % dsp->view.bytes);
		} else {
			elapsed = false;
		}
		spin_unlock_irqrestore(&dsp->period_lock, flags);
		if (error) {
			snd_pcm_stop_xrun(dsp->substream);
			return;
		}
		if (elapsed)
			snd_pcm_period_elapsed(dsp->substream);
	}
}

static void mt8901_afe_dsp_period_work(struct work_struct *work)
{
	struct mt8901_afe_dsp *dsp = container_of(work, struct mt8901_afe_dsp, period_work);
	struct n1x_adsp_pcm_position position;
	unsigned long flags;
	bool pending;
	int error;
	int ret;

	if (dsp->capture) {
		mt8901_afe_dsp_capture_work(dsp);
		return;
	}
	spin_lock_irqsave(&dsp->period_lock, flags);
	pending = dsp->period_pending;
	dsp->period_pending = false;
	error = dsp->notification_error;
	spin_unlock_irqrestore(&dsp->period_lock, flags);
	if (READ_ONCE(dsp->closing) || !READ_ONCE(dsp->running))
		return;
	if (error) {
		snd_pcm_stop_xrun(dsp->substream);
		return;
	}
	if (!pending)
		return;
	ret = dsp->position(dsp->primary, &position);
	if (ret)
		snd_pcm_stop_xrun(dsp->substream);
	else if (position.valid)
		snd_pcm_period_elapsed(dsp->substream);
}

static void mt8901_afe_dsp_period(void *data,
				 const struct n1x_adsp_pcm_position *position, int error)
{
	struct mt8901_afe_dsp *dsp = data;
	unsigned long flags;
	u32 offset, delta, bytes;
	bool pending = false;

	/* Nonatomic PCM stream locks may sleep: defer ALSA calls out of hard IRQ. */
	if (READ_ONCE(dsp->closing) || !READ_ONCE(dsp->running))
		return;
	spin_lock_irqsave(&dsp->period_lock, flags);
	if (error) {
		dsp->notification_error = error;
		pending = true;
	} else if (position->valid) {
		bytes = dsp->view.bytes;
		offset = position->at_end ? bytes : position->byte_offset;
		delta = offset >= dsp->irq_offset ? offset - dsp->irq_offset :
			bytes - dsp->irq_offset + offset;
		dsp->irq_offset = offset;
		if (dsp->capture) {
			if (delta >= bytes - dsp->capture_pending_bytes)
				dsp->notification_error = -EPIPE;
			else
				dsp->capture_pending_bytes += delta;
			pending = delta || dsp->notification_error;
			goto unlock;
		}
		dsp->period_remainder += delta;
		if (dsp->period_remainder >= dsp->period_bytes) {
			dsp->period_remainder %= dsp->period_bytes;
			dsp->period_pending = true;
			pending = true;
		}
	}
unlock:
	spin_unlock_irqrestore(&dsp->period_lock, flags);
	if (pending)
		schedule_work(&dsp->period_work);
}

int mt8901_afe_dsp_startup(struct snd_pcm_substream *substream, struct snd_soc_dai *dai)
{
	struct mtk_base_afe *afe = snd_soc_dai_get_drvdata(dai);
	struct mt8901_afe_private *priv = afe->platform_priv;
	struct snd_pcm_runtime *runtime = substream->runtime;
	struct mt8901_afe_dsp *dsp;
	struct device *dev;
	size_t ring_max;
	int ret;

	if (substream->stream == SNDRV_PCM_STREAM_PLAYBACK) {
		if (!dsp_playback ||
		    (dai->id != MT8901_AFE_MEMIF_DL0 && dai->id != MT8901_AFE_MEMIF_DL1))
			return 0;
	} else if (substream->stream == SNDRV_PCM_STREAM_CAPTURE) {
		if (!dsp_capture || dai->id != MT8901_AFE_MEMIF_UL1)
			return 0;
	} else {
		return -EINVAL;
	}
	if (!substream->pcm->nonatomic || !priv->sram || priv->dsp[substream->stream])
		return -EOPNOTSUPP;
	ring_max = mt8901_afe_sram_size(afe);
	if (ring_max <= MT8901_DSP_IPC_BYTES)
		return -ENOSPC;
	/* Two persistent 32 KiB rings plus playback's 2 KiB IPC fit in the
	 * shared 80 KiB SRAM. One direction cannot starve the other.
	 */
	ring_max = min_t(size_t, (ring_max - MT8901_DSP_IPC_BYTES) / 2, 32768);

	dsp = kzalloc_obj(*dsp);
	if (!dsp)
		return -ENOMEM;
	dsp->capture = substream->stream == SNDRV_PCM_STREAM_CAPTURE;
	dsp->abi = symbol_get(n1x_adsp_primary_abi);
	dsp->open = symbol_get(n1x_adsp_primary_open_pcm);
	dsp->rebind = symbol_get(n1x_adsp_primary_rebind);
	dsp->configure = symbol_get(n1x_adsp_primary_configure);
	dsp->prepare = symbol_get(n1x_adsp_primary_prepare_pcm);
	dsp->pcm_view = symbol_get(n1x_adsp_primary_pcm_view);
	dsp->commit = symbol_get(n1x_adsp_primary_commit);
	dsp->start = symbol_get(n1x_adsp_primary_start);
	dsp->stop = symbol_get(n1x_adsp_primary_stop);
	dsp->set_period = symbol_get(n1x_adsp_primary_set_period);
	dsp->position = symbol_get(n1x_adsp_primary_position);
	dsp->close = symbol_get(n1x_adsp_primary_close);
	if (!dsp->abi || !dsp->open || !dsp->rebind || !dsp->configure ||
	    !dsp->prepare || !dsp->pcm_view ||
	    !dsp->commit || !dsp->start || !dsp->stop || !dsp->set_period ||
	    !dsp->position || !dsp->close) {
		ret = -EOPNOTSUPP;
		goto free;
	}
	if (dsp->abi() != N1X_ADSP_PRIMARY_ABI) {
		ret = -EOPNOTSUPP;
		goto free;
	}
	runtime->hw.channels_max = min(runtime->hw.channels_max, 2U);
	runtime->hw.buffer_bytes_max = min_t(unsigned int, runtime->hw.buffer_bytes_max, ring_max);
	runtime->hw.period_bytes_max = min_t(unsigned int, runtime->hw.period_bytes_max, ring_max / 2);
	runtime->hw.info &= ~(SNDRV_PCM_INFO_PAUSE | SNDRV_PCM_INFO_RESUME |
			      SNDRV_PCM_INFO_NO_PERIOD_WAKEUP);
	dev = n1x_adsp_find_device(afe->dev, dsp->capture ? "NVDA8301" : "NVDA8303");
	if (!dev) {
		ret = -ENODEV;
		goto free;
	}
	dsp->primary = dsp->open(dev, substream);
	put_device(dev);
	if (IS_ERR(dsp->primary)) {
		ret = PTR_ERR(dsp->primary);
		goto free;
	}
	dsp->substream = substream;
	INIT_WORK(&dsp->period_work, mt8901_afe_dsp_period_work);
	spin_lock_init(&dsp->period_lock);
	priv->dsp[substream->stream] = dsp;
	return 0;
free:
	mt8901_afe_dsp_put_ops(dsp);
	kfree(dsp);
	return ret;
}

int mt8901_afe_dsp_hw_params(struct snd_pcm_substream *substream)
{
	struct mt8901_afe_dsp *dsp = mt8901_afe_dsp_get(substream);

	if (!dsp)
		return 0;
	if (dsp->error)
		return dsp->error;
	if (dsp->closing) {
		struct snd_soc_pcm_runtime *rtd = snd_soc_substream_to_rtd(substream);
		struct device *dev, *afe = snd_soc_rtd_to_cpu(rtd, 0)->dev;

		/* ALSA allows HW_FREE/HW_PARAMS without closing the file. The
		 * old owner has been retired; reopen and rebind its persistent ring.
		 */
		dev = n1x_adsp_find_device(afe, dsp->capture ? "NVDA8301" : "NVDA8303");
		if (!dev)
			return -ENODEV;
		dsp->primary = dsp->open(dev, substream);
		put_device(dev);
		if (IS_ERR(dsp->primary)) {
			dsp->error = PTR_ERR(dsp->primary);
			dsp->primary = NULL;
			return dsp->error;
		}
		dsp->closing = false;
	}
	/* Reprogramming a configured ring requires HW_FREE first. */
	return dsp->configured ? -EALREADY : 0;
}

int mt8901_afe_dsp_prepare(struct snd_pcm_substream *substream, struct snd_soc_dai *dai)
{
	struct mt8901_afe_dsp *dsp = mt8901_afe_dsp_get(substream);
	struct snd_pcm_runtime *runtime = substream->runtime;
	struct mt8901_afe_sram_buffer *buffer;
	struct n1x_adsp_primary_pcm_params params;
	int ret;

	if (!dsp)
		return 0;
	if (dsp->error)
		return dsp->error;
	if (dsp->closing)
		return -EALREADY;
	if (dsp->prepared)
		return dsp->samples ? -EALREADY : 0;
	/* ALSA assigns runtime format/period fields after hw_params returns. */
	if (!dsp->configured) {
		buffer = NULL;
		ret = dsp->rebind(dsp->primary, substream);
		if (ret == -ENOENT) {
			/* One persistent maximum-size ring avoids growing allocations
			 * across normal PipeWire close/open and format changes.
			 */
			buffer = mt8901_afe_sram_reserve(dai->dev, runtime->hw.buffer_bytes_max);
			if (IS_ERR(buffer))
				return PTR_ERR(buffer);
			ret = mt8901_afe_sram_bind(buffer, substream);
		}
		params = (struct n1x_adsp_primary_pcm_params){
			.rate = runtime->rate, .channels = runtime->channels,
			.sample_bits = runtime->sample_bits,
			.period_frames = runtime->period_size, .periods = runtime->periods,
		};
		if (!ret)
			ret = dsp->configure(dsp->primary, &params, &buffer);
		if (buffer)
			mt8901_afe_sram_release(buffer);
		if (ret)
			goto failed;
		dsp->configured = true;
	}
	ret = dsp->prepare(dsp->primary);
	if (!ret)
		ret = dsp->pcm_view(dsp->primary, &dsp->view);
	if (!ret && (!dsp->view.area || dsp->view.bytes != snd_pcm_lib_buffer_bytes(substream)))
		ret = -EINVAL;
	dsp->period_bytes = frames_to_bytes(runtime, runtime->period_size);
	if (!ret)
		ret = dsp->set_period(dsp->primary, mt8901_afe_dsp_period, dsp);
	if (ret)
		goto failed;
	dsp->listening = true;
	dsp->appl_ptr = 0;
	dsp->capture_pending_bytes = 0;
	dsp->capture_offset = 0;
	dsp->notification_error = 0;
	dsp->irq_offset = 0;
	dsp->period_remainder = 0;
	dsp->period_pending = false;
	dsp->prepared = true;
	return 0;
failed:
	dsp->error = ret;
	return ret;
}

static int mt8901_afe_dsp_ack(struct snd_soc_component *component,
			      struct snd_pcm_substream *substream)
{
	struct mt8901_afe_dsp *dsp = mt8901_afe_dsp_get(substream);
	struct snd_pcm_runtime *runtime = substream->runtime;
	snd_pcm_uframes_t appl, delta;
	size_t offset, bytes, first;
	int ret;

	if (!dsp)
		return 0;
	if (dsp->capture)
		return 0;
	if (dsp->error)
		return dsp->error;
	if (!dsp->prepared || dsp->closing)
		return -EBADFD;
	appl = READ_ONCE(runtime->control->appl_ptr);
	if (appl >= runtime->boundary || dsp->appl_ptr >= runtime->boundary)
		return -EINVAL;
	delta = appl >= dsp->appl_ptr ? appl - dsp->appl_ptr :
		runtime->boundary - dsp->appl_ptr + appl;
	if (!delta)
		return 0;
	/* Reject rewinds and advances beyond the ring; ALSA owns availability. */
	if (delta > runtime->buffer_size)
		return -EINVAL;
	offset = frames_to_bytes(runtime, dsp->appl_ptr % runtime->buffer_size);
	bytes = frames_to_bytes(runtime, delta);
	first = min(bytes, dsp->view.bytes - offset);
	memcpy(dsp->view.area + offset, runtime->dma_area + offset, first);
	if (bytes > first)
		memcpy(dsp->view.area, runtime->dma_area, bytes - first);
	offset = frames_to_bytes(runtime, appl % runtime->buffer_size);
	/* Preserve the full-ring boundary; base would describe an empty ring. */
	ret = dsp->commit(dsp->primary, offset ? offset : dsp->view.bytes);
	if (ret)
		dsp->error = ret;
	else {
		dsp->appl_ptr = appl;
		dsp->samples = true;
	}
	return ret;
}

static snd_pcm_uframes_t mt8901_afe_dsp_pointer(struct snd_soc_component *component,
					     struct snd_pcm_substream *substream)
{
	struct mt8901_afe_dsp *dsp = mt8901_afe_dsp_get(substream);
	struct n1x_adsp_pcm_position position;
	int ret;

	if (!dsp)
		return mtk_afe_pcm_pointer(component, substream);
	if (dsp->error || dsp->closing)
		return SNDRV_PCM_POS_XRUN;
	if (!dsp->prepared)
		return 0;
	if (dsp->capture) {
		u32 offset;

		if (READ_ONCE(dsp->notification_error))
			return SNDRV_PCM_POS_XRUN;
		/* Pair with capture_work's release: samples precede the visible cursor. */
		offset = smp_load_acquire(&dsp->capture_offset);
		return bytes_to_frames(substream->runtime, offset);
	}
	ret = dsp->position(dsp->primary, &position);
	if (ret)
		return SNDRV_PCM_POS_XRUN;
	return position.valid ? bytes_to_frames(substream->runtime, position.byte_offset) : 0;
}

int mt8901_afe_dsp_trigger(struct snd_pcm_substream *substream, int command)
{
	struct mt8901_afe_dsp *dsp = mt8901_afe_dsp_get(substream);
	int ret;

	if (!dsp || dsp->closing || (!dsp->prepared && command == SNDRV_PCM_TRIGGER_START))
		return -EBADFD;
	switch (command) {
	case SNDRV_PCM_TRIGGER_START:
		if (dsp->error)
			return dsp->error;
		WRITE_ONCE(dsp->running, true);
		ret = dsp->start(dsp->primary);
		if (!ret) {
			struct snd_soc_dai *dai;

			dai = snd_soc_rtd_to_cpu(snd_soc_substream_to_rtd(substream), 0);
			ret = mt8901_afe_sram_start_pcm(substream, dai);
			if (ret) {
				int stop_ret = dsp->stop(dsp->primary);

				if (stop_ret)
					ret = stop_ret;
			}
		}
		if (ret)
			WRITE_ONCE(dsp->running, false);
		break;
	case SNDRV_PCM_TRIGGER_STOP:
	case SNDRV_PCM_TRIGGER_SUSPEND:
		WRITE_ONCE(dsp->running, false);
		ret = dsp->stop(dsp->primary);
		if (!ret) {
			dsp->prepared = false;
			dsp->samples = false;
		}
		break;
	default:
		return -EINVAL;
	}
	if (ret)
		dsp->error = ret;
	return ret;
}

static int mt8901_afe_dsp_sync_stop(struct snd_soc_component *component,
				    struct snd_pcm_substream *substream)
{
	struct mt8901_afe_dsp *dsp = mt8901_afe_dsp_get(substream);

	/* ALSA calls sync_stop outside its stream lock. STOP only disables queuing. */
	if (dsp)
		cancel_work_sync(&dsp->period_work);
	else if (substream->pcm->card->sync_irq > 0)
		synchronize_irq(substream->pcm->card->sync_irq);
	return 0;
}

int mt8901_afe_dsp_hw_free(struct snd_pcm_substream *substream, struct snd_soc_dai *dai)
{
	struct mt8901_afe_dsp *dsp = mt8901_afe_dsp_get(substream);
	int ret = 0;

	if (!dsp || dsp->closing)
		return 0;
	WRITE_ONCE(dsp->closing, true);
	WRITE_ONCE(dsp->running, false);
	/* Drain both IRQ callbacks and queued users of the primary handle. */
	if (dsp->primary && dsp->listening)
		dsp->set_period(dsp->primary, NULL, NULL);
	cancel_work_sync(&dsp->period_work);
	/* close retires the borrowed AFE substream even after a task error. */
	if (dsp->primary) {
		ret = dsp->close(dsp->primary);
		dsp->primary = NULL;
	}
	if (ret)
		dsp->error = ret;
	else
		dsp->configured = dsp->prepared = dsp->listening = dsp->samples = false;
	return ret;
}

void mt8901_afe_dsp_shutdown(struct snd_pcm_substream *substream, struct snd_soc_dai *dai)
{
	struct mtk_base_afe *afe = snd_soc_dai_get_drvdata(dai);
	struct mt8901_afe_private *priv = afe->platform_priv;
	struct mt8901_afe_dsp *dsp = mt8901_afe_dsp_get(substream);

	if (!dsp)
		return;
	mt8901_afe_dsp_hw_free(substream, dai);
	priv->dsp[substream->stream] = NULL;
	mt8901_afe_dsp_put_ops(dsp);
	kfree(dsp);
}

static int mt8901_afe_dsp_component_probe(struct snd_soc_component *component)
{
	return mtk_afe_pcm_platform.probe(component);
}

const struct snd_soc_component_driver mt8901_afe_dsp_platform = {
	.name = AFE_PCM_NAME,
	.pointer = mt8901_afe_dsp_pointer,
	.ack = mt8901_afe_dsp_ack,
	.sync_stop = mt8901_afe_dsp_sync_stop,
	.pcm_new = mtk_afe_pcm_new,
	.probe = mt8901_afe_dsp_component_probe,
};
