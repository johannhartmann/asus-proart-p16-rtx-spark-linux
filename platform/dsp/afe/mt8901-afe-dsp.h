/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef MT8901_AFE_DSP_H
#define MT8901_AFE_DSP_H

#include <sound/pcm.h>

struct mtk_base_afe;
struct snd_soc_dai;
struct snd_soc_component;
struct snd_soc_component_driver;

int mt8901_afe_dsp_startup(struct snd_pcm_substream *substream, struct snd_soc_dai *dai);
int mt8901_afe_dsp_hw_params(struct snd_pcm_substream *substream);
int mt8901_afe_dsp_prepare(struct snd_pcm_substream *substream, struct snd_soc_dai *dai);
bool mt8901_afe_dsp_active(struct snd_pcm_substream *substream);
bool mt8901_afe_dsp_enabled(void);
int mt8901_afe_dsp_trigger(struct snd_pcm_substream *substream, int command);
int mt8901_afe_dsp_hw_free(struct snd_pcm_substream *substream, struct snd_soc_dai *dai);
void mt8901_afe_dsp_shutdown(struct snd_pcm_substream *substream, struct snd_soc_dai *dai);
extern const struct snd_soc_component_driver mt8901_afe_dsp_platform;

#endif
