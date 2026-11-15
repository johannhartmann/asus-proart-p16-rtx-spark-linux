// SPDX-License-Identifier: GPL-2.0-only
/* Unmodified functions from Linux 7.2.8 sound/soc/soc-pcm.c.
 * OS edges and dpcm_fe_dai_do_trigger() are supplied by test_sram.py.
 */
static void dpcm_set_fe_update_state(struct snd_soc_pcm_runtime *fe,
				     int stream, enum snd_soc_dpcm_update state)
{
	struct snd_pcm_substream *substream =
		snd_soc_dpcm_get_substream(fe, stream);

	snd_pcm_stream_lock_irq(substream);
	if (state == SND_SOC_DPCM_UPDATE_NO && fe->dpcm[stream].trigger_pending) {
		dpcm_fe_dai_do_trigger(substream,
				       fe->dpcm[stream].trigger_pending - 1);
		fe->dpcm[stream].trigger_pending = 0;
	}
	fe->dpcm[stream].runtime_update = state;
	snd_pcm_stream_unlock_irq(substream);
}

static int dpcm_fe_dai_trigger(struct snd_pcm_substream *substream, int cmd)
{
	struct snd_soc_pcm_runtime *fe = snd_soc_substream_to_rtd(substream);
	int stream = substream->stream;

	/* if FE's runtime_update is already set, we're in race;
	 * process this trigger later at exit
	 */
	if (fe->dpcm[stream].runtime_update != SND_SOC_DPCM_UPDATE_NO) {
		fe->dpcm[stream].trigger_pending = cmd + 1;
		return 0; /* delayed, assuming it's successful */
	}

	/* we're alone, let's trigger */
	return dpcm_fe_dai_do_trigger(substream, cmd);
}
