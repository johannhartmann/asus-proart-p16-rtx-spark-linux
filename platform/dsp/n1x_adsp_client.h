/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef N1X_ADSP_CLIENT_H
#define N1X_ADSP_CLIENT_H

#include "n1x_adsp_ipc.h"
#include "n1x_adsp_pcm.h"

struct device;
struct n1x_adsp_primary;
struct mt8901_afe_sram_buffer;
struct snd_pcm_substream;

#ifdef __KERNEL__
#include <linux/acpi.h>
#include <linux/platform_device.h>

/* Referenced unique sibling in the consumer's firmware scope. NULL consumer
 * is reserved for standalone validation modules and requires global uniqueness.
 * Never pick the first device when firmware associations are ambiguous.
 */
static inline struct device *n1x_adsp_find_device(struct device *consumer, const char *hid)
{
	struct acpi_device *adev = NULL, *found = NULL;
	struct acpi_device *parent = NULL;
	struct device *dev;

	if (consumer) {
		if (!ACPI_COMPANION(consumer))
			return NULL;
		parent = acpi_dev_parent(ACPI_COMPANION(consumer));
		if (!parent)
			return NULL;
	}
	while ((adev = acpi_dev_get_next_match_dev(adev, hid, NULL, -1))) {
		if (consumer && acpi_dev_parent(adev) != parent)
			continue;
		if (found) {
			acpi_dev_put(found);
			acpi_dev_put(adev);
			return NULL;
		}
		found = acpi_dev_get(adev);
	}
	if (!found)
		return NULL;
	dev = bus_find_device_by_acpi_dev(&platform_bus_type, found);
	acpi_dev_put(found);
	return dev;
}
#endif

#define N1X_ADSP_PRIMARY_ABI 2U

/* Query the typed playback client contract before opening a task. No firmware
 * access. ABI 2 adds retained-ring rebind, successful close/open reuse and
 * STOP/PREPARE/START recovery to the original position/retirement contract.
 */
__u32 n1x_adsp_primary_abi(void);

struct n1x_adsp_primary_pcm_params {
	__u32 rate, channels, sample_bits, period_frames, periods;
};

struct n1x_adsp_primary_pcm_view {
	void *area;
	size_t bytes;
};

struct n1x_adsp_ipc_reply {
	__u8 packet[N1X_ADSP_IPC_BYTES];
};

/* Kernel service clients supply token=0 and ack_mode=1. The transport assigns
 * the token and serializes each request through its matching acknowledgment.
 * A successful exchange does not establish service success or DMA quiescence.
 * The client validates the service reply and retains any published buffers
 * until that service's release contract is satisfied. Errors are not retryable.
 * The reply is unchanged on error. This call sleeps and requires process context.
 * Tasks 7 and 16 must use the dedicated playback lifecycle API below.
 */
int n1x_adsp_transfer(struct device *dev,
		      const struct n1x_adsp_ipc_request *request,
		      struct n1x_adsp_ipc_reply *reply);

/* Register the primary playback task's four message buffers on the core
 * selected by the speaker/headphone firmware properties (route 2, HiFi1).
 * Route 3 selects a different native task graph and is not implemented here.
 * Registered buffers
 * remain owned by the DSP boot allocation; this call does not open a stream.
 * Repeated calls after success reuse the registration. A failed sequence
 * cannot be replayed or release its buffers. This call sleeps.
 */
int n1x_adsp_prepare_primary(struct device *dev);

/* Open the primary task exclusively after registering its message buffers.
 * Returns an owned handle or ERR_PTR(). No PCM configuration or START is sent.
 * A failed firmware request prevents reopening until device reinitialization.
 * Successful HWFREE/CLOSE permits reopening with the same retained buffers.
 * This call sleeps and requires process context.
 */
struct n1x_adsp_primary *n1x_adsp_primary_open(struct device *dev);

/* Reattach the persistent AFE ring after successful HWFREE/CLOSE and a fresh
 * OPEN. ENOENT means no ring exists yet; reserve/bind an initial lease instead.
 * No firmware request, allocation or release. Requires serialized ALSA setup.
 */
int n1x_adsp_primary_rebind(struct n1x_adsp_primary *primary,
			    struct snd_pcm_substream *substream);

/* Register and open processing task 16 with AFE-owned SRAM message memory,
 * then configure the task-7 host ring, task-16 AFE ring and bridge with
 * commands 4, 0x201 and 4. Sends no PREPARE or START. The AFE must remain in
 * non-running stream setup, serialized by the caller. Host and AFE formats
 * must match; period sizes/counts may differ. Missing AFE support is rejected
 * before any firmware request. A firmware-stage failure is terminal.
 *
 * After successful rebind, pass *sram=NULL to reuse the retained ring.
 * Otherwise, on publication, ownership of *sram transfers to the DSP boot state and
 * *sram becomes NULL, including if the following request fails. Otherwise
 * the caller still owns its lease. Published memory remains retained until
 * verified whole-core shutdown, which is not implemented yet. A failure before
 * PCM publication can still retain published IPC SRAM. This call sleeps.
 */
int n1x_adsp_primary_configure(struct n1x_adsp_primary *primary,
			       const struct n1x_adsp_primary_pcm_params *params,
			       struct mt8901_afe_sram_buffer **sram);

/* Prepare task 16 with commands 0x203 (hardware) and 3 (bridge), then task 7
 * with commands 0x203 and 3 (both host). Revalidates the published AFE endpoint
 * during non-running ALSA setup;
 * the caller serializes setup/teardown. Repeated success sends no further IPC.
 * A firmware-stage failure is terminal and retains both rings. This does not
 * enable the AFE memif, start a stream or release DMA. Before DSP PREPARE,
 * the AFE owner programs its memif address with checked writes.
 * After all four acknowledgements, the owner prepares the disabled IRQ's
 * period counter, rate and active clock domain. Requires AFE endpoint ABI 2.
 * A programming failure is terminal. This call sleeps.
 */
int n1x_adsp_primary_prepare_pcm(struct n1x_adsp_primary *primary);

/* Return the configured coherent host-ring view to its owning kernel client.
 * Valid only for this handle's lifetime. No userspace mapping is provided.
 * The output is unchanged on error. This call sleeps.
 */
int n1x_adsp_primary_pcm_view(struct n1x_adsp_primary *primary,
			      struct n1x_adsp_primary_pcm_view *view);

/* Publish a prepared host ring's write cursor after filling samples through
 * pcm_view. The caller owns availability and serializes sample writes/handle
 * lifetime. byte_offset is frame-aligned and may equal the ring size.
 * Orders completed sample writes before the registered descriptor, preserving
 * the last validated read address and advancing the write-generation counter.
 * Sends no mailbox command. A late power error can follow publication; that
 * error is terminal and the client must not retry or release published memory.
 * Requires process context. This call sleeps.
 */
int n1x_adsp_primary_commit(struct n1x_adsp_primary *primary, __u32 byte_offset);

/* Start the prepared route-2 task-16/task-7 chain in normal playback mode 0.
 * Requires published samples and AFE endpoint ABI 2 IRQ readiness. The Linux
 * audio client owns its DAPM/codec routing; this call does not program a gain
 * or channel merge or enable a CPU memif. Repeated success sends no IPC.
 * Firmware-stage failures are terminal and may leave hardware active.
 * Sleeps; the caller serializes sample, stream and handle lifetime.
 */
int n1x_adsp_primary_start(struct n1x_adsp_primary *primary);

/* STOP task 7 then task 16, then disable/clear the owned HiFi1 IRQ. Successful
 * repetition sends no IPC or register writes. Synchronizes and detaches the
 * period listener; the client must drain its own queued work before freeing
 * listener data. Does not release memory or prove core quiescence. Restart
 * requires a fresh PREPARE, listener and sample publication; no buffers are freed.
 * A failed request is terminal. Requires process context; sleeps.
 */
int n1x_adsp_primary_stop(struct n1x_adsp_primary *primary);

/* Register one consumed-data listener, or pass NULL to detach it. The listener runs
 * in IRQ context and must not sleep or call sleeping DSP APIs. Its position
 * snapshot is valid only during the call. A negative error reports a rejected
 * notification; no buffer address from that packet is used.
 * One message does not necessarily correspond to one ALSA period.
 * Detach and close wait for in-flight IRQ callbacks before returning, so the
 * caller may then free listener data. Do not hold a lock needed by the listener.
 * Drain work queued by the listener separately before freeing its data.
 * Requires process context and serialized handle lifetime. This call sleeps.
 */
int n1x_adsp_primary_set_period(struct n1x_adsp_primary *primary,
			       void (*period)(void *data,
					      const struct n1x_adsp_pcm_position *position,
					      int error), void *data);

/* Copy the latest consumed position after prepare. Before the first notification,
 * valid is false and the offset is zero. Returns a cached notification/transport error
 * without changing the output. May be called from IRQ context while the caller
 * retains the handle; this does not acknowledge or publish any firmware data.
 */
int n1x_adsp_primary_position(struct n1x_adsp_primary *primary,
			     struct n1x_adsp_pcm_position *position);

/* Stop a started stream, then send primary HWFREE/CLOSE and, if opened,
 * processing HWFREE/AFE-HWFREE/CLOSE, stopping at the first error.
 * Consumes the handle on
 * every result; the caller must not use it again. Published DMA remains owned
 * by the DSP driver. Failure leaves the task unavailable for another open.
 * This call sleeps and requires process context.
 */
int n1x_adsp_primary_close(struct n1x_adsp_primary *primary);

#endif
