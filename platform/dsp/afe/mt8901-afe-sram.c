// SPDX-License-Identifier: GPL-2.0-only
#include <linux/atomic.h>
#include <linux/err.h>
#include <linux/genalloc.h>
#include <linux/io.h>
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/pm_runtime.h>
#include <linux/property.h>
#include <linux/regmap.h>
#include <linux/slab.h>
#include <sound/mt8901-afe-sram.h>

#include "mt8901-afe-common.h"
#include "mt8901-afe-dsp.h"
#include "mt8901-reg.h"
#include "../common/mtk-afe-fe-dai.h"

#define MT8901_SRAM_ALIGN 16

struct mt8901_afe_sram {
	struct gen_pool *pool;
	void __iomem *base;
	u32 cpu, vad, dsp, bytes;
	atomic_t users;
	atomic_t retention_users, sleeping_users;
	void *snapshot;
	bool sleep_prepared, sleep_saved;
	struct mt8901_afe_sram_buffer *memif[MT8901_AFE_MEMIF_NUM];
};

struct mt8901_afe_sram_buffer {
	struct device *dev;
	struct mt8901_afe_sram *sram;
	unsigned long address;
	size_t bytes;
	bool published, ipc;
	bool retention, asleep;
	bool prepared, irq_prepared, irq_stopped;
	int prepare_error, irq_error, irq_stop_error;
	bool started;
	int start_error;
	struct snd_pcm_substream *substream;
	struct mt8901_afe_sram_endpoint endpoint;
};

static void mt8901_afe_sram_destroy(void *data)
{
	struct mt8901_afe_sram *sram = data;

	/* Leases pin the module; driver bind attributes are suppressed. */
	if (WARN_ON(atomic_read(&sram->users)))
		return;
	gen_pool_destroy(sram->pool);
}

int mt8901_afe_sram_init(struct mtk_base_afe *afe)
{
	static const char * const properties[] = {
		"acpi-asd-sram-size",
		"acpi-asd-sram-cpu-view",
		"acpi-asd-sram-vad-view",
		"acpi-asd-sram-adsp-view",
	};
	struct mt8901_afe_private *priv = afe->platform_priv;
	struct device *dev = afe->dev;
	struct mt8901_afe_sram *sram;
	struct fwnode_handle *node;
	struct resource resource;
	u32 values[ARRAY_SIZE(properties)], count, version;
	void *group;
	unsigned int i;
	int ret;

	if (!device_property_present(dev, "acpi-asd-sram-resource-list"))
		return 0;
	ret = device_property_read_u32(dev, "acpi-asd-hw-ver", &version);
	if (ret)
		return ret;
	ret = device_property_read_u32(dev, "acpi-asd-sram-resource-list", &count);
	if (ret)
		return ret;
	if (version != 1 || count != 1)
		return -ENODEV;
	node = device_get_named_child_node(dev, "acpi-asd-afe-sram-subproperties");
	if (!node)
		return -ENODEV;
	for (i = 0; i < ARRAY_SIZE(properties); i++) {
		ret = fwnode_property_read_u32(node, properties[i], &values[i]);
		if (ret)
			break;
	}
	fwnode_handle_put(node);
	if (ret)
		return ret;
	if (!values[0] || !IS_ALIGNED(values[0], MT8901_SRAM_ALIGN))
		return -EINVAL;
	for (i = 1; i < ARRAY_SIZE(values); i++)
		if (!values[i] || !IS_ALIGNED(values[i], MT8901_SRAM_ALIGN) ||
		    values[0] - 1 > U32_MAX - values[i])
			return -ERANGE;
	group = devres_open_group(dev, NULL, GFP_KERNEL);
	if (!group)
		return -ENOMEM;
	sram = devm_kzalloc(dev, sizeof(*sram), GFP_KERNEL);
	if (!sram) {
		ret = -ENOMEM;
		goto release;
	}
	sram->snapshot = devm_kzalloc(dev, values[0], GFP_KERNEL);
	if (!sram->snapshot) {
		ret = -ENOMEM;
		goto release;
	}
	resource = (struct resource)DEFINE_RES_MEM(values[1], values[0]);
	resource.name = "mt8901-afe-sram";
	sram->base = devm_ioremap_resource(dev, &resource);
	if (IS_ERR(sram->base)) {
		ret = PTR_ERR(sram->base);
		goto release;
	}
	sram->pool = gen_pool_create(4, NUMA_NO_NODE);
	if (!sram->pool) {
		ret = -ENOMEM;
		goto release;
	}
	ret = gen_pool_add_virt(sram->pool, (unsigned long)sram->base,
				values[1], values[0], NUMA_NO_NODE);
	if (ret) {
		gen_pool_destroy(sram->pool);
		goto release;
	}
	atomic_set(&sram->users, 0);
	atomic_set(&sram->retention_users, 0);
	atomic_set(&sram->sleeping_users, 0);
	sram->bytes = values[0];
	sram->cpu = values[1];
	sram->vad = values[2];
	sram->dsp = values[3];
	ret = devm_add_action_or_reset(dev, mt8901_afe_sram_destroy, sram);
	if (ret)
		goto release;
	priv->sram = sram;
	devres_close_group(dev, group);
	return 0;
release:
	devres_release_group(dev, group);
	return ret;
}

size_t mt8901_afe_sram_size(struct mtk_base_afe *afe)
{
	struct mt8901_afe_private *priv = afe->platform_priv;

	return priv->sram ? priv->sram->bytes : 0;
}

bool mt8901_afe_sram_busy(struct mtk_base_afe *afe)
{
	struct mt8901_afe_private *priv = afe->platform_priv;

	return priv->sram && atomic_read(&priv->sram->users) && !priv->sram->sleep_saved;
}

static bool mt8901_afe_sram_stream(int id, int stream)
{
	return (stream == SNDRV_PCM_STREAM_PLAYBACK &&
		(id == MT8901_AFE_MEMIF_DL0 || id == MT8901_AFE_MEMIF_DL1)) ||
	       (stream == SNDRV_PCM_STREAM_CAPTURE && id == MT8901_AFE_MEMIF_UL1);
}

static unsigned int mt8901_afe_sram_target(int memif)
{
	/* Endpoint route enum 2 (HiFi1) is distinct from task-core enum 3. */
	return memif == MT8901_AFE_MEMIF_UL1 ? AFE_IRQ_MCU_DSP_EN : AFE_IRQ_MCU_DSP3_EN;
}

static bool mt8901_afe_sram_enable_valid(const struct mtk_base_memif_data *data, int id)
{
	int reg = id == MT8901_AFE_MEMIF_UL1 ? AFE_VUL1_CON0 :
		  id == MT8901_AFE_MEMIF_DL1 ? AFE_DL1_CON0 : AFE_DL0_CON0;

	return (id == MT8901_AFE_MEMIF_DL0 || id == MT8901_AFE_MEMIF_DL1 ||
		id == MT8901_AFE_MEMIF_UL1) &&
	       data && data->enable_reg == reg && data->enable_shift == DL_ON_SFT;
}

/* Caller owns the ALSA stream lifetime; the returned card device is referenced. */
struct device *mt8901_afe_pcm_card_device(struct snd_pcm_substream *substream)
{
	struct snd_soc_pcm_runtime *rtd;
	struct snd_soc_dai *dai;
	struct mtk_base_afe *afe;
	struct device *card = ERR_PTR(-EINVAL);

	if (!substream || !substream->pcm || !substream->runtime)
		return card;
	rtd = snd_soc_substream_to_rtd(substream);
	if (!rtd || !rtd->card || !snd_soc_card_is_instantiated(rtd->card) ||
	    !rtd->card->dev || substream->pcm->card != rtd->card->snd_card)
		return card;
	dai = snd_soc_rtd_to_cpu(rtd, 0);
	if (!dai || !dai->dev || !mt8901_afe_sram_stream(dai->id, substream->stream))
		return card;
	device_lock(dai->dev);
	if (dai->dev->driver != &mt8901_afe_pcm_driver.driver)
		goto unlock;
	afe = snd_soc_dai_get_drvdata(dai);
	if (!afe || afe->dev != dai->dev || dai->id >= afe->memif_size ||
	    afe->memif[dai->id].substream != substream)
		goto unlock;
	card = get_device(rtd->card->dev);
unlock:
	device_unlock(dai->dev);
	return card;
}
EXPORT_SYMBOL_GPL(mt8901_afe_pcm_card_device);

struct mt8901_afe_sram_buffer *mt8901_afe_sram_reserve(struct device *dev, size_t bytes)
{
	struct mt8901_afe_sram_buffer *buffer;
	struct mt8901_afe_private *priv;
	struct mtk_base_afe *afe;
	unsigned long address;
	int ret;

	if (!dev || !bytes || !IS_ALIGNED(bytes, MT8901_SRAM_ALIGN))
		return ERR_PTR(-EINVAL);
	buffer = kzalloc_obj(*buffer);
	if (!buffer)
		return ERR_PTR(-ENOMEM);
	device_lock(dev);
	if (dev->driver != &mt8901_afe_pcm_driver.driver) {
		ret = -ENODEV;
		goto unlock;
	}
	afe = dev_get_drvdata(dev);
	priv = afe->platform_priv;
	if (!priv->sram) {
		ret = -EOPNOTSUPP;
		goto unlock;
	}
	if (priv->sram->sleep_prepared || priv->sram->sleep_saved) {
		ret = -EBUSY;
		goto unlock;
	}
	if (bytes > priv->sram->bytes) {
		ret = -EINVAL;
		goto unlock;
	}
	if (!try_module_get(THIS_MODULE)) {
		ret = -ENODEV;
		goto unlock;
	}
	if (!pm_runtime_enabled(dev)) {
		ret = -EHOSTDOWN;
		goto put_module;
	}
	ret = pm_runtime_resume_and_get(dev);
	if (ret < 0)
		goto put_module;
	address = gen_pool_alloc(priv->sram->pool, bytes);
	if (!address) {
		ret = -ENOMEM;
		pm_runtime_put(dev);
		goto put_module;
	}
	memset_io((void __iomem *)address, 0, bytes);
	buffer->dev = get_device(dev);
	buffer->sram = priv->sram;
	buffer->address = address;
	buffer->bytes = bytes;
	atomic_inc(&priv->sram->users);
	device_unlock(dev);
	return buffer;
put_module:
	module_put(THIS_MODULE);
unlock:
	device_unlock(dev);
	kfree(buffer);
	return ERR_PTR(ret);
}
EXPORT_SYMBOL_GPL(mt8901_afe_sram_reserve);

struct mt8901_afe_sram_buffer *
mt8901_afe_sram_reserve_ipc(struct mt8901_afe_sram_buffer *peer, size_t bytes)
{
	struct mt8901_afe_sram_buffer *buffer;

	if (IS_ERR_OR_NULL(peer) || peer->ipc || !peer->substream ||
	    !bytes || bytes > 4096 || !IS_ALIGNED(bytes, 1024))
		return ERR_PTR(-EINVAL);
	buffer = mt8901_afe_sram_reserve(peer->dev, bytes);
	if (!IS_ERR(buffer))
		buffer->ipc = true;
	return buffer;
}
EXPORT_SYMBOL_GPL(mt8901_afe_sram_reserve_ipc);

int mt8901_afe_sram_publish_ipc(struct mt8901_afe_sram_buffer *buffer)
{
	int ret = 0;

	if (IS_ERR_OR_NULL(buffer))
		return -EINVAL;
	device_lock(buffer->dev);
	if (buffer->dev->driver != &mt8901_afe_pcm_driver.driver)
		ret = -ENODEV;
	else if (!buffer->ipc || buffer->substream)
		ret = -EINVAL;
	else {
		/* Publish complete IPC SRAM contents before a firmware registration. */
		wmb();
		buffer->published = true;
	}
	device_unlock(buffer->dev);
	return ret;
}
EXPORT_SYMBOL_GPL(mt8901_afe_sram_publish_ipc);

int mt8901_afe_sram_view(struct mt8901_afe_sram_buffer *buffer,
			struct mt8901_afe_sram_view *view)
{
	unsigned long offset;

	if (IS_ERR_OR_NULL(buffer) || !view)
		return -EINVAL;
	offset = buffer->address - (unsigned long)buffer->sram->base;
	view->area = (void __iomem *)buffer->address;
	view->cpu_address = (u64)buffer->sram->cpu + offset;
	view->afe_address = (u64)buffer->sram->vad + offset;
	view->dsp_address = (u64)buffer->sram->dsp + offset;
	view->bytes = buffer->bytes;
	return 0;
}
EXPORT_SYMBOL_GPL(mt8901_afe_sram_view);

int mt8901_afe_sram_startup(struct snd_pcm_substream *substream, struct snd_soc_dai *dai)
{
	struct mtk_base_afe *afe = snd_soc_dai_get_drvdata(dai);
	struct mt8901_afe_private *priv = afe->platform_priv;
	int ret;

	if (dai->id < 0 || dai->id >= MT8901_AFE_MEMIF_NUM)
		return -EINVAL;
	device_lock(afe->dev);
	ret = 0;
	if (priv->sram) {
		struct mt8901_afe_sram_buffer *buffer = priv->sram->memif[dai->id];

		if (priv->sram->sleep_prepared || priv->sram->sleep_saved)
			ret = -EBUSY;
		else if (buffer &&
			 (!mt8901_afe_dsp_enabled() || !mt8901_afe_sram_stream(dai->id, substream->stream) ||
			  !buffer->retention || buffer->substream || !buffer->published))
			ret = -EBUSY;
	}
	if (!ret)
		ret = mtk_afe_fe_startup(substream, dai);
	device_unlock(afe->dev);
	return ret;
}

static int mt8901_afe_sram_bind_common(struct mt8901_afe_sram_buffer *buffer,
				       struct snd_pcm_substream *substream, bool rebind)
{
	struct mt8901_afe_sram_endpoint endpoint = {.abi_version = 2};
	struct snd_pcm_runtime *runtime;
	struct snd_soc_dai *dai;
	struct mtk_base_afe *afe;
	u64 frames;
	u32 frame_bytes;
	int ret = 0, id, irq;

	if (IS_ERR_OR_NULL(buffer) || buffer->ipc || !substream || !substream->runtime)
		return -EINVAL;
	runtime = substream->runtime;
	if (snd_pcm_running(substream))
		return -EBUSY;
	if (!runtime->rate || !runtime->channels || runtime->channels > 2 ||
	    (runtime->sample_bits != 16 && runtime->sample_bits != 32) ||
	    !runtime->period_size || runtime->period_size > 0x7fffffff ||
	    runtime->periods < 2 || runtime->periods > 0x7fffffff)
		return -EINVAL;
	frame_bytes = runtime->channels * (runtime->sample_bits / 8);
	frames = (u64)runtime->period_size * runtime->periods;
	if (frames > 0xffffffffU / frame_bytes)
		return -ERANGE;
	if (frames * frame_bytes > buffer->bytes ||
	    !IS_ALIGNED(frames * frame_bytes, MT8901_SRAM_ALIGN))
		return -EINVAL;
	dai = snd_soc_rtd_to_cpu(snd_soc_substream_to_rtd(substream), 0);
	id = dai->id;
	if (!mt8901_afe_sram_stream(id, substream->stream) &&
	    !(substream->stream == SNDRV_PCM_STREAM_PLAYBACK &&
	      id >= 0 && id < MT8901_AFE_MEMIF_UL_START))
		return -EOPNOTSUPP;
	device_lock(buffer->dev);
	if (buffer->dev->driver != &mt8901_afe_pcm_driver.driver || dai->dev != buffer->dev) {
		ret = -ENODEV;
		goto unlock;
	}
	if (buffer->sram->sleep_prepared || buffer->sram->sleep_saved) {
		ret = -EBUSY;
		goto unlock;
	}
	afe = dev_get_drvdata(buffer->dev);
	if (id < 0 || id >= MT8901_AFE_MEMIF_NUM || id >= afe->memif_size ||
	    snd_soc_dai_get_drvdata(dai) != afe || afe->memif[id].substream != substream) {
		ret = -EBUSY;
		goto unlock;
	}
	irq = afe->memif[id].irq_usage;
	if (irq != id || irq >= afe->irqs_size || !afe->irqs[irq].irq_occupyed ||
	    buffer->substream || buffer->published != rebind ||
	    (buffer->sram->memif[id] && (!rebind || buffer->sram->memif[id] != buffer))) {
		ret = -EBUSY;
		goto unlock;
	}
	if (rebind) {
		u32 control;

		if (buffer->sram->memif[buffer->endpoint.memif] != buffer ||
		    (id == MT8901_AFE_MEMIF_UL1) != (buffer->endpoint.memif == MT8901_AFE_MEMIF_UL1) ||
		    buffer->prepare_error || buffer->irq_error || buffer->irq_stop_error ||
		    buffer->start_error || buffer->started) {
			ret = -ENOTRECOVERABLE;
			goto unlock;
		}
		ret = regmap_read(afe->regmap, AFE_IRQ0_MCU_CFG0 + buffer->endpoint.irq * 8, &control);
		if (ret)
			goto unlock;
		if (control & 1) {
			ret = -EBUSY;
			goto unlock;
		}
		/* The old stream was stopped and closed by the DSP owner. Check
		 * both endpoints before moving this still-published reservation.
		 */
		if (id != buffer->endpoint.memif) {
			const struct mtk_base_memif_data *old = afe->memif[buffer->endpoint.memif].data;
			const struct mtk_base_memif_data *next = afe->memif[id].data;

			if (!mt8901_afe_sram_enable_valid(old, buffer->endpoint.memif) ||
			    !mt8901_afe_sram_enable_valid(next, id)) {
				ret = -EOPNOTSUPP;
				goto unlock;
			}
			ret = regmap_read(afe->regmap, old->enable_reg, &control);
			if (!ret && !(control & BIT(old->enable_shift)))
				ret = regmap_read(afe->regmap, AFE_IRQ0_MCU_CFG0 + irq * 8, &control);
			else if (!ret)
				ret = -EBUSY;
			if (ret || (control & 1)) {
				ret = ret ?: -EBUSY;
				goto unlock;
			}
			ret = regmap_read(afe->regmap, next->enable_reg, &control);
			if (ret || (control & BIT(next->enable_shift))) {
				ret = ret ?: -EBUSY;
				goto unlock;
			}
		}
		buffer->sram->memif[buffer->endpoint.memif] = NULL;
		buffer->prepared = false;
		buffer->irq_prepared = false;
		buffer->irq_stopped = false;
	}
	mt8901_afe_sram_view(buffer, &endpoint.memory);
	endpoint.memory.bytes = frames * frame_bytes;
	endpoint.rate = runtime->rate;
	endpoint.channels = runtime->channels;
	endpoint.sample_bits = runtime->sample_bits;
	endpoint.period_frames = runtime->period_size;
	endpoint.periods = runtime->periods;
	endpoint.memif = id;
	endpoint.irq = irq;
	buffer->endpoint = endpoint;
	buffer->substream = substream;
	buffer->sram->memif[id] = buffer;
unlock:
	device_unlock(buffer->dev);
	return ret;
}

int mt8901_afe_sram_bind(struct mt8901_afe_sram_buffer *buffer,
			 struct snd_pcm_substream *substream)
{
	return mt8901_afe_sram_bind_common(buffer, substream, false);
}
EXPORT_SYMBOL_GPL(mt8901_afe_sram_bind);

int mt8901_afe_sram_rebind(struct mt8901_afe_sram_buffer *buffer,
			   struct snd_pcm_substream *substream)
{
	return mt8901_afe_sram_bind_common(buffer, substream, true);
}
EXPORT_SYMBOL_GPL(mt8901_afe_sram_rebind);

static bool mt8901_afe_sram_endpoint_valid(struct mt8901_afe_sram_buffer *buffer,
					 struct mtk_base_afe *afe, bool allow_running)
{
	struct snd_pcm_runtime *runtime;
	struct mt8901_afe_sram_endpoint *endpoint = &buffer->endpoint;

	if (afe->memif[endpoint->memif].substream != buffer->substream)
		return false;
	runtime = buffer->substream->runtime;
	return runtime && (allow_running || !snd_pcm_running(buffer->substream)) &&
	       runtime->rate == endpoint->rate && runtime->channels == endpoint->channels &&
	       runtime->sample_bits == endpoint->sample_bits &&
	       runtime->period_size == endpoint->period_frames &&
	       runtime->periods == endpoint->periods;
}

int mt8901_afe_sram_endpoint(struct mt8901_afe_sram_buffer *buffer,
			    struct mt8901_afe_sram_endpoint *endpoint, size_t bytes)
{
	struct mtk_base_afe *afe;
	int ret = 0;

	if (IS_ERR_OR_NULL(buffer) || !endpoint || bytes != sizeof(*endpoint))
		return -EINVAL;
	device_lock(buffer->dev);
	if (buffer->dev->driver != &mt8901_afe_pcm_driver.driver || !buffer->substream) {
		ret = -ENODEV;
		goto unlock;
	}
	afe = dev_get_drvdata(buffer->dev);
	if (!mt8901_afe_sram_endpoint_valid(buffer, afe, false)) {
		ret = -EBUSY;
		goto unlock;
	}
	*endpoint = buffer->endpoint;
	endpoint->published = buffer->published;
	endpoint->irq_prepared = buffer->irq_prepared;
unlock:
	device_unlock(buffer->dev);
	return ret;
}
EXPORT_SYMBOL_GPL(mt8901_afe_sram_endpoint);

static int mt8901_afe_sram_prepare_owner(struct mt8901_afe_sram_buffer *buffer,
					struct mtk_base_afe **owner, bool allow_running)
{
	struct mtk_base_afe *afe;
	struct snd_soc_dai *dai;

	if (buffer->dev->driver != &mt8901_afe_pcm_driver.driver ||
	    !buffer->substream || !buffer->published)
		return -ENODEV;
	afe = dev_get_drvdata(buffer->dev);
	if (!mt8901_afe_sram_endpoint_valid(buffer, afe, allow_running))
		return -EBUSY;
	dai = snd_soc_rtd_to_cpu(snd_soc_substream_to_rtd(buffer->substream), 0);
	if (dai->dev != buffer->dev || dai->id != buffer->endpoint.memif ||
	    snd_soc_dai_get_drvdata(dai) != afe ||
	    buffer->sram->memif[dai->id] != buffer ||
	    afe->memif[dai->id].irq_usage != buffer->endpoint.irq ||
	    !afe->irqs[buffer->endpoint.irq].irq_occupyed)
		return -EBUSY;
	*owner = afe;
	return 0;
}

int mt8901_afe_sram_prepare(struct mt8901_afe_sram_buffer *buffer)
{
	struct mtk_base_afe_memif *memif;
	const struct mtk_base_memif_data *data;
	struct mtk_base_afe *afe;
	int registers[4];
	u32 values[4];
	unsigned int i;
	int ret;

	if (IS_ERR_OR_NULL(buffer) || buffer->ipc)
		return -EINVAL;
	device_lock(buffer->dev);
	ret = mt8901_afe_sram_prepare_owner(buffer, &afe, false);
	if (ret)
		goto unlock;
	ret = buffer->prepare_error;
	if (ret || buffer->prepared)
		goto unlock;
	memif = &afe->memif[buffer->endpoint.memif];
	data = memif->data;
	/* This MT8901 layout uses separate base/end MSBs and no prepare callback. */
	if (!data || data->msb_reg > 0 || data->msb_end_reg > 0 ||
	    afe->get_memif_pbuf_size || buffer->endpoint.memory.afe_address > U32_MAX ||
	    buffer->endpoint.memory.afe_address + buffer->endpoint.memory.bytes - 1 > U32_MAX) {
		ret = -EOPNOTSUPP;
		goto unlock;
	}
	registers[0] = data->reg_ofs_base;
	registers[1] = data->reg_ofs_end;
	registers[2] = data->reg_ofs_base_msb;
	registers[3] = data->reg_ofs_end_msb;
	for (i = 0; i < ARRAY_SIZE(registers); i++) {
		if (registers[i] <= 0 || !IS_ALIGNED(registers[i], 4)) {
			ret = -EOPNOTSUPP;
			goto unlock;
		}
	}
	values[0] = buffer->endpoint.memory.afe_address;
	values[1] = values[0] + buffer->endpoint.memory.bytes - 1;
	values[2] = 0;
	values[3] = 0;
	/* The shared address helper discards write errors. Stop at the first one. */
	for (i = 0; i < ARRAY_SIZE(registers); i++) {
		ret = regmap_write(afe->regmap, registers[i], values[i]);
		if (ret) {
			buffer->prepare_error = ret;
			goto unlock;
		}
	}
	memif->dma_area = (void __force *)buffer->endpoint.memory.area;
	memif->dma_addr = buffer->endpoint.memory.afe_address;
	memif->dma_bytes = buffer->endpoint.memory.bytes;
	buffer->prepared = true;
unlock:
	device_unlock(buffer->dev);
	return ret;
}
EXPORT_SYMBOL_GPL(mt8901_afe_sram_prepare);

/* Both normal and prepared-after-resume START must restore volatile IRQ config. */
static int mt8901_afe_sram_program_irq(struct mt8901_afe_sram_buffer *buffer,
				       struct mtk_base_afe *afe)
{
	const struct mtk_base_irq_data *irq;
	u32 control;
	int ret, fs, domain, cfg;

	irq = afe->irqs[buffer->endpoint.irq].irq_data;
	cfg = AFE_IRQ0_MCU_CFG0 + buffer->endpoint.irq * 8;
	if (!irq || !afe->irq_fs || irq->id != buffer->endpoint.irq ||
	    irq->irq_fs_reg != cfg || irq->irq_fs_shift != 4 || irq->irq_fs_maskbit != 0x1f ||
	    irq->irq_domain_reg != cfg || irq->irq_domain_shift != 9 ||
	    irq->irq_domain_maskbit != 7 || irq->irq_cnt_reg != cfg + 4 ||
	    irq->irq_cnt_shift || irq->irq_cnt_maskbit != 0xffffff ||
	    irq->irq_en_reg != cfg || irq->irq_en_shift)
		return -EOPNOTSUPP;
	fs = afe->irq_fs(buffer->substream, buffer->endpoint.rate);
	domain = mt8901_afe_sram_domain(afe, buffer->endpoint.memif);
	if (fs < 0 || domain < 0)
		return fs < 0 ? fs : domain;
	if (fs > 0x1f || domain > 7 || buffer->endpoint.period_frames > 0xffffff)
		return -ERANGE;
	ret = regmap_read(afe->regmap, cfg, &control);
	if (ret)
		return ret;
	if (control & BIT(irq->irq_en_shift))
		return -EBUSY;
	ret = regmap_update_bits(afe->regmap, cfg + 4, 0xffffff,
				 buffer->endpoint.period_frames);
	if (!ret)
		ret = regmap_update_bits(afe->regmap, cfg, 0x1f << 4, fs << 4);
	if (!ret)
		ret = regmap_update_bits(afe->regmap, cfg, 7 << 9, domain << 9);
	if (ret)
		buffer->irq_error = ret;
	return ret;
}

int mt8901_afe_sram_prepare_irq(struct mt8901_afe_sram_buffer *buffer)
{
	struct mtk_base_afe *afe;
	int ret;

	if (IS_ERR_OR_NULL(buffer) || buffer->ipc)
		return -EINVAL;
	device_lock(buffer->dev);
	ret = mt8901_afe_sram_prepare_owner(buffer, &afe, false);
	if (ret)
		goto unlock;
	ret = buffer->prepare_error ?: buffer->irq_error ?: buffer->irq_stop_error ?:
		buffer->start_error;
	if (ret || buffer->irq_prepared)
		goto unlock;
	if (!buffer->prepared) {
		ret = -EINVAL;
		goto unlock;
	}
	ret = mt8901_afe_sram_program_irq(buffer, afe);
	if (ret)
		goto unlock;
	buffer->irq_prepared = true;
	buffer->irq_stopped = false;
unlock:
	device_unlock(buffer->dev);
	return ret;
}
EXPORT_SYMBOL_GPL(mt8901_afe_sram_prepare_irq);

/* The DSP task ACK is not a hardware trigger. The AFE still owns the memif
 * and IRQ. Start only the published DL0 lease after both task START ACKs,
 * with the IRQ routed to native core 3 (HiFi1), not to the host MCU handler.
 */
int mt8901_afe_sram_start_pcm(struct snd_pcm_substream *substream, struct snd_soc_dai *dai)
{
	const struct mtk_base_memif_data *data;
	const struct mtk_base_irq_data *irq;
	struct mt8901_afe_sram_buffer *buffer;
	struct mt8901_afe_private *priv;
	struct mtk_base_afe *afe;
	u32 bit;
	int ret, cfg;

	if (!substream || !dai || !dai->dev ||
	    !mt8901_afe_sram_stream(dai->id, substream->stream))
		return -EINVAL;
	device_lock(dai->dev);
	if (dai->dev->driver != &mt8901_afe_pcm_driver.driver) {
		ret = -ENODEV;
		goto unlock;
	}
	afe = snd_soc_dai_get_drvdata(dai);
	priv = afe->platform_priv;
	buffer = priv->sram ? priv->sram->memif[dai->id] : NULL;
	if (!buffer || buffer->ipc || !buffer->published || buffer->substream != substream) {
		ret = -EINVAL;
		goto unlock;
	}
	if (buffer->sram->sleep_prepared || buffer->sram->sleep_saved) {
		ret = -EBUSY;
		goto unlock;
	}
	ret = mt8901_afe_sram_prepare_owner(buffer, &afe, true);
	if (ret)
		goto unlock;
	ret = buffer->prepare_error ?: buffer->irq_error ?: buffer->irq_stop_error ?:
		buffer->start_error;
	if (ret || buffer->started)
		goto unlock;
	if (!buffer->prepared || !buffer->irq_prepared || buffer->irq_stopped) {
		ret = -EINVAL;
		goto unlock;
	}
	data = afe->memif[dai->id].data;
	irq = afe->irqs[buffer->endpoint.irq].irq_data;
	cfg = AFE_IRQ0_MCU_CFG0 + buffer->endpoint.irq * 8;
	if (!mt8901_afe_sram_enable_valid(data, dai->id) ||
	    !irq || irq->id != buffer->endpoint.irq || irq->irq_en_reg != cfg ||
	    irq->irq_en_shift || irq->irq_mask_reg != AFE_IRQ_MCU_EN ||
	    irq->irq_mask_shift != buffer->endpoint.irq) {
		ret = -EOPNOTSUPP;
		goto unlock;
	}
	ret = mt8901_afe_sram_program_irq(buffer, afe);
	if (ret)
		goto unlock;
	bit = BIT(buffer->endpoint.irq);
	ret = regmap_update_bits(afe->regmap, AFE_IRQ_MCU_EN, bit, 0);
	if (!ret)
		ret = regmap_update_bits(afe->regmap, mt8901_afe_sram_target(dai->id), bit, bit);
	if (!ret)
		ret = regmap_update_bits(afe->regmap, data->enable_reg,
					 BIT(data->enable_shift), BIT(data->enable_shift));
	if (!ret)
		mt8901_afe_sram_prefetch(afe, dai->id, substream);
	if (!ret)
		ret = regmap_update_bits(afe->regmap, cfg, 1, 1);
	if (ret)
		buffer->start_error = ret;
	else
		buffer->started = true;
unlock:
	device_unlock(dai->dev);
	return ret;
}

int mt8901_afe_sram_stop_irq(struct mt8901_afe_sram_buffer *buffer, unsigned int core)
{
	const struct mtk_base_memif_data *data;
	const struct mtk_base_irq_data *irq;
	struct mtk_base_afe *afe;
	u32 bit, clear;
	int cfg, ret;

	if (IS_ERR_OR_NULL(buffer) || buffer->ipc)
		return -EINVAL;
	/* This argument is the endpoint route, not the task-core enum. */
	if (core != (buffer->endpoint.memif == MT8901_AFE_MEMIF_UL1 ? 3 : 2))
		return -EOPNOTSUPP;
	device_lock(buffer->dev);
	ret = mt8901_afe_sram_prepare_owner(buffer, &afe, true);
	if (ret)
		goto unlock;
	ret = buffer->prepare_error ?: buffer->irq_error ?: buffer->irq_stop_error;
	if (ret || buffer->irq_stopped)
		goto unlock;
	if (!buffer->irq_prepared) {
		ret = -EINVAL;
		goto unlock;
	}
	irq = afe->irqs[buffer->endpoint.irq].irq_data;
	data = afe->memif[buffer->endpoint.memif].data;
	cfg = AFE_IRQ0_MCU_CFG0 + buffer->endpoint.irq * 8;
	if (!mt8901_afe_sram_enable_valid(data, buffer->endpoint.memif) ||
	    !irq || irq->id != buffer->endpoint.irq ||
	    irq->irq_en_reg != cfg || irq->irq_en_shift ||
	    irq->irq_clr_reg != cfg + 4 || irq->irq_clr_shift != 31 ||
	    irq->irq_mask_reg != AFE_IRQ_MCU_EN ||
	    irq->irq_mask_shift != buffer->endpoint.irq) {
		ret = -EOPNOTSUPP;
		goto unlock;
	}
	bit = BIT(buffer->endpoint.irq);
	buffer->irq_prepared = false;
	ret = regmap_update_bits(afe->regmap, data->enable_reg, BIT(data->enable_shift), 0);
	if (!ret)
		ret = regmap_update_bits(afe->regmap, cfg, 1, 0);
	if (!ret)
		ret = regmap_read(afe->regmap, cfg + 4, &clear);
	if (!ret)
		ret = regmap_update_bits(afe->regmap, cfg + 4, BIT(31), ~clear & BIT(31));
	if (!ret)
		ret = regmap_update_bits(afe->regmap, AFE_IRQ_MCU_EN, bit, 0);
	if (!ret)
		ret = regmap_update_bits(afe->regmap, mt8901_afe_sram_target(buffer->endpoint.memif), bit, 0);
	if (ret)
		buffer->irq_stop_error = ret;
	else {
		buffer->started = false;
		buffer->irq_stopped = true;
		buffer->irq_prepared = false;
	}
unlock:
	device_unlock(buffer->dev);
	return ret;
}
EXPORT_SYMBOL_GPL(mt8901_afe_sram_stop_irq);

void mt8901_afe_sram_retire(struct mt8901_afe_sram_buffer *buffer)
{
	if (IS_ERR_OR_NULL(buffer) || buffer->ipc)
		return;
	device_lock(buffer->dev);
	/* The retained lease must not outlive a borrowed ALSA substream pointer. */
	if (buffer->published)
		buffer->substream = NULL;
	device_unlock(buffer->dev);
}
EXPORT_SYMBOL_GPL(mt8901_afe_sram_retire);

int mt8901_afe_sram_publish(struct mt8901_afe_sram_buffer *buffer)
{
	struct mtk_base_afe *afe;

	if (IS_ERR_OR_NULL(buffer))
		return -EINVAL;
	device_lock(buffer->dev);
	if (buffer->dev->driver != &mt8901_afe_pcm_driver.driver || !buffer->substream) {
		device_unlock(buffer->dev);
		return -ENODEV;
	}
	afe = dev_get_drvdata(buffer->dev);
	if (!mt8901_afe_sram_endpoint_valid(buffer, afe, false)) {
		device_unlock(buffer->dev);
		return -EBUSY;
	}
	/* Complete SRAM writes before the caller can submit a device address. */
	wmb();
	buffer->published = true;
	device_unlock(buffer->dev);
	return 0;
}
EXPORT_SYMBOL_GPL(mt8901_afe_sram_publish);

int mt8901_afe_sram_release(struct mt8901_afe_sram_buffer *buffer)
{
	struct device *dev;
	int ret;

	if (IS_ERR_OR_NULL(buffer))
		return -EINVAL;
	dev = buffer->dev;
	device_lock(dev);
	if (buffer->published) {
		device_unlock(dev);
		return -EBUSY;
	}
	if (buffer->substream)
		buffer->sram->memif[buffer->endpoint.memif] = NULL;
	gen_pool_free(buffer->sram->pool, buffer->address, buffer->bytes);
	atomic_dec(&buffer->sram->users);
	ret = pm_runtime_put_sync(dev);
	device_unlock(dev);
	kfree(buffer);
	put_device(dev);
	module_put(THIS_MODULE);
	return ret < 0 ? ret : 0;
}
EXPORT_SYMBOL_GPL(mt8901_afe_sram_release);

int mt8901_afe_sram_allow_retention(struct mt8901_afe_sram_buffer *buffer)
{
	int ret = 0;

	if (IS_ERR_OR_NULL(buffer))
		return -EINVAL;
	device_lock(buffer->dev);
	if (buffer->dev->driver != &mt8901_afe_pcm_driver.driver) {
		ret = -ENODEV;
	} else if (!buffer->published || (buffer->sram->sleep_prepared && !buffer->retention)) {
		ret = -EBUSY;
	} else if (!buffer->retention) {
		buffer->retention = true;
		atomic_inc(&buffer->sram->retention_users);
	}
	device_unlock(buffer->dev);
	return ret;
}
EXPORT_SYMBOL_GPL(mt8901_afe_sram_allow_retention);

int mt8901_afe_sram_suspend(struct mt8901_afe_sram_buffer *buffer)
{
	int ret = 0;

	if (IS_ERR_OR_NULL(buffer))
		return -EINVAL;
	device_lock(buffer->dev);
	if (buffer->dev->driver != &mt8901_afe_pcm_driver.driver) {
		ret = -ENODEV;
	} else if (!buffer->retention || !buffer->sram->sleep_prepared ||
		   (buffer->substream && snd_pcm_running(buffer->substream))) {
		ret = -EBUSY;
	} else if (buffer->asleep) {
		ret = -EALREADY;
	} else {
		buffer->asleep = true;
		atomic_inc(&buffer->sram->sleeping_users);
	}
	device_unlock(buffer->dev);
	return ret;
}
EXPORT_SYMBOL_GPL(mt8901_afe_sram_suspend);

int mt8901_afe_sram_resume(struct mt8901_afe_sram_buffer *buffer)
{
	int ret = 0;

	if (IS_ERR_OR_NULL(buffer))
		return -EINVAL;
	device_lock(buffer->dev);
	if (buffer->dev->driver != &mt8901_afe_pcm_driver.driver) {
		ret = -ENODEV;
	} else if (!buffer->asleep || buffer->sram->sleep_saved) {
		ret = -EHOSTDOWN;
	} else {
		buffer->asleep = false;
		atomic_dec(&buffer->sram->sleeping_users);
	}
	device_unlock(buffer->dev);
	return ret;
}
EXPORT_SYMBOL_GPL(mt8901_afe_sram_resume);

/* PM callbacks run under the AFE device lock. Consumers' DSP -> AFE links
 * order their D3 votes before snapshot, and restoration before their D0.
 */
int mt8901_afe_sram_pm_prepare(struct mtk_base_afe *afe)
{
	struct mt8901_afe_private *priv = afe->platform_priv;
	struct mt8901_afe_sram *sram = priv->sram;
	unsigned int i;

	if (!sram)
		return 0;
	for (i = 0; i < ARRAY_SIZE(sram->memif); i++) {
		struct mt8901_afe_sram_buffer *buffer = sram->memif[i];

		if (buffer && (buffer->prepare_error || buffer->irq_error ||
			       buffer->start_error || buffer->irq_stop_error))
			return -ENOTRECOVERABLE;
	}
	if (sram->sleep_saved ||
	    atomic_read(&sram->users) != atomic_read(&sram->retention_users))
		return -EBUSY;
	sram->sleep_prepared = true;
	return 0;
}

void mt8901_afe_sram_pm_complete(struct mtk_base_afe *afe)
{
	struct mt8901_afe_private *priv = afe->platform_priv;

	if (priv->sram)
		priv->sram->sleep_prepared = false;
}

int mt8901_afe_sram_pm_save(struct mtk_base_afe *afe)
{
	struct mt8901_afe_private *priv = afe->platform_priv;
	struct mt8901_afe_sram *sram = priv->sram;

	if (!sram || !atomic_read(&sram->users))
		return 0;
	if (!sram->sleep_prepared ||
	    atomic_read(&sram->users) != atomic_read(&sram->sleeping_users))
		return -EBUSY;
	memcpy_fromio(sram->snapshot, sram->base, sram->bytes);
	sram->sleep_saved = true;
	return 0;
}

void mt8901_afe_sram_pm_restore(struct mtk_base_afe *afe)
{
	struct mt8901_afe_private *priv = afe->platform_priv;
	struct mt8901_afe_sram *sram = priv->sram;

	if (!sram || !sram->sleep_saved)
		return;
	memcpy_toio(sram->base, sram->snapshot, sram->bytes);
	/* Publish the complete restored SRAM before consumers can clear votes. */
	wmb();
	sram->sleep_saved = false;
}
