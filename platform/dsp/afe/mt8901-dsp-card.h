/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef MT8901_DSP_CARD_H
#define MT8901_DSP_CARD_H

#include <sound/n1x_adsp_client.h>

/* Register the firmware-backed DSP components as card suppliers. The ASoC
 * core then stops ALSA streams before any DSP device enters system sleep.
 * No codec/AFE is made a consumer of the DSP: the DSP owns SRAM references
 * in the other direction, so such a link would create a dependency cycle.
 */
static int mt8901_card_add_dsps(struct snd_soc_card *card, bool enabled)
{
	static const char * const hids[] = {"NVDA8301", "NVDA8302", "NVDA8303"};
	struct snd_soc_aux_dev *aux;
	unsigned int i, count = card->num_aux_devs;

	if (!enabled)
		return 0;
	aux = devm_kcalloc(card->dev, count + ARRAY_SIZE(hids), sizeof(*aux), GFP_KERNEL);
	if (!aux)
		return -ENOMEM;
	if (count)
		memcpy(aux, card->aux_dev, count * sizeof(*aux));
	for (i = 0; i < ARRAY_SIZE(hids); i++) {
		struct snd_soc_component *component;
		struct device *dsp;

		dsp = n1x_adsp_find_device(card->dev->parent, hids[i]);
		if (!dsp)
			return -EPROBE_DEFER;
		component = snd_soc_lookup_component(dsp, "n1x-adsp");
		if (component)
			aux[count + i].dlc.name = devm_kstrdup(card->dev, component->name,
							       GFP_KERNEL);
		put_device(dsp);
		if (!component)
			return -EPROBE_DEFER;
		if (!aux[count + i].dlc.name)
			return -ENOMEM;
	}
	card->aux_dev = aux;
	card->num_aux_devs = count + ARRAY_SIZE(hids);
	return 0;
}
#endif
