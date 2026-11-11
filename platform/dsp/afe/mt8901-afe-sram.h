/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef MT8901_AFE_SRAM_H
#define MT8901_AFE_SRAM_H

#include <linux/compiler_types.h>
#include <linux/types.h>

struct device;
struct snd_pcm_substream;
struct mt8901_afe_sram_buffer;

struct mt8901_afe_sram_view {
	void __iomem *area;
	u64 cpu_address;
	u64 afe_address;
	u64 dsp_address;
	size_t bytes;
};

struct mt8901_afe_sram_endpoint {
	u32 abi_version;
	struct mt8901_afe_sram_view memory;
	u32 rate, channels, sample_bits, period_frames, periods;
	u8 memif, irq;
	bool published, irq_prepared;
};

/* Return a referenced, instantiated sound-card device for a real owned DL0/DL1
 * playback or UL1 capture stream, or ERR_PTR(). No firmware or power operation. The caller
 * serializes stream lifetime and must put_device() the returned reference.
 */
struct device *mt8901_afe_pcm_card_device(struct snd_pcm_substream *substream);

/* Reserve and zero a multiple of 16 bytes from the AFE-owned SRAM pool.
 * Holds a device, module and runtime-PM reference until an unpublished lease
 * is released. Returns an exclusive handle or ERR_PTR(); sleeps.
 */
struct mt8901_afe_sram_buffer *mt8901_afe_sram_reserve(struct device *dev, size_t bytes);

/* Reserve 1..4 KiB of IPC SRAM from a bound PCM lease's owner, in 1 KiB
 * multiples. The caller serializes the peer's lifetime. The new lease has
 * independent references and cannot bind a PCM substream. This call sleeps.
 */
struct mt8901_afe_sram_buffer *
mt8901_afe_sram_reserve_ipc(struct mt8901_afe_sram_buffer *peer, size_t bytes);

/* Mark an IPC lease published before registering its address with firmware.
 * Published IPC leases retain the same suspend/unload guards as PCM leases.
 * They cannot be released until a verified DSP quiesce contract is added.
 */
int mt8901_afe_sram_publish_ipc(struct mt8901_afe_sram_buffer *buffer);

/* Read the three address views for this allocation. The client selects the
 * view required by its service protocol; these are not interchangeable DMA
 * addresses. This copies metadata only and leaves the output unchanged on error.
 */
int mt8901_afe_sram_view(struct mt8901_afe_sram_buffer *buffer,
			struct mt8901_afe_sram_view *view);

/* Bind an unpublished lease during non-running PCM stream setup, after
 * the AFE DAI's hw_params. Derives memif, IRQ and format from that substream;
 * its complete ring must fit the reservation. A bound memif cannot start
 * another substream until the lease is released. The caller serializes ALSA
 * setup/teardown around this call. It does not program or start the memif.
 */
int mt8901_afe_sram_bind(struct mt8901_afe_sram_buffer *buffer,
			 struct snd_pcm_substream *substream);

/* Reattach a retired, published lease after acknowledged DSP HWFREE/CLOSE.
 * The DSP owner alone may call this; it must serialize task and stream state.
 * Allows DL0/DL1 playback rebinding or unchanged UL1 capture. Requires idle
 * old/new IRQs and memifs, healthy owner state and a ring fitting the allocation.
 * No memory or PM references are freed.
 */
int mt8901_afe_sram_rebind(struct mt8901_afe_sram_buffer *buffer,
			   struct snd_pcm_substream *substream);

/* Return a bound endpoint only while its original AFE substream still owns
 * the memif and its format is unchanged. bytes must equal sizeof(*endpoint).
 * The output is unchanged on error. This call sleeps.
 */
int mt8901_afe_sram_endpoint(struct mt8901_afe_sram_buffer *buffer,
			    struct mt8901_afe_sram_endpoint *endpoint, size_t bytes);

/* Program the published lease's memif address, checking each write.
 * Requires non-running, unchanged ALSA setup, serialized by the caller.
 * Repeated success performs no writes.
 * A programming failure is terminal: partial register writes can have exposed
 * the address, so the lease and its references remain retained. Does not
 * enable the memif or its IRQ. This call sleeps.
 */
int mt8901_afe_sram_prepare(struct mt8901_afe_sram_buffer *buffer);

/* After firmware PREPARE, program the disabled IRQ's counter, rate and active
 * AFE clock domain. Requires successful address preparation and unchanged,
 * non-running ALSA setup. Repeated success writes nothing. A write failure
 * is terminal and retains the lease. Sets endpoint ABI 2's irq_prepared flag
 * only after complete success. Does not enable or route the IRQ; sleeps.
 */
int mt8901_afe_sram_prepare_irq(struct mt8901_afe_sram_buffer *buffer);

/* After acknowledged task STOPs, disable the owned memif, disable/clear
 * its IRQ and remove its MCU and DSP target bits. The route argument is
 * endpoint enum 2 for HiFi1 or 3 for primary HiFi5, not a task-core enum.
 * Allows the still-running ALSA STOP callback, but requires
 * unchanged ownership and
 * format. Repeated success writes nothing; failed I/O is terminal. Does not
 * prove whole-core quiescence; no published memory may be released. The caller
 * serializes handle lifetime. This call sleeps.
 */
int mt8901_afe_sram_stop_irq(struct mt8901_afe_sram_buffer *buffer, unsigned int core);

/* Forget a published lease's ALSA substream before that substream is freed.
 * Caller first stops or abandons its task and synchronizes its callbacks.
 * Retains the allocation, memif reservation and power/module references.
 * Future endpoint/prepare operations fail. No MMIO or DMA release; sleeps.
 */
void mt8901_afe_sram_retire(struct mt8901_afe_sram_buffer *buffer);

/* Call after binding and before publishing a buffer address to firmware or
 * hardware. A published lease cannot be released by the current API and blocks
 * AFE runtime suspend. System sleep requires every owner
 * to participate in the retained-SRAM protocol.
 * Service acknowledgements do not establish whole-core DMA quiescence.
 */
int mt8901_afe_sram_publish(struct mt8901_afe_sram_buffer *buffer);

/* Release an unpublished lease. EBUSY leaves a published handle and all its
 * resources intact. Otherwise consumes the handle; a negative runtime-PM
 * result reports a suspend failure after the lease itself has been released.
 * The caller serializes operations on each handle. This call sleeps.
 */
int mt8901_afe_sram_release(struct mt8901_afe_sram_buffer *buffer);

/* Retained system-sleep protocol for published DSP-owned SRAM. The owner must
 * have a DSP -> AFE PM link and participate in the sound card's ASoC ordering.
 * allow_retention() is a capability declaration during successful setup.
 * suspend() follows acknowledged DSP D3 and a stopped ALSA stream; resume()
 * follows restored AFE SRAM and acknowledged DSP D0. Neither releases memory.
 */
int mt8901_afe_sram_allow_retention(struct mt8901_afe_sram_buffer *buffer);
int mt8901_afe_sram_suspend(struct mt8901_afe_sram_buffer *buffer);
int mt8901_afe_sram_resume(struct mt8901_afe_sram_buffer *buffer);

#endif
