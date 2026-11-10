/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef N1X_ADSP_PCM_H
#define N1X_ADSP_PCM_H

#include "n1x_adsp_ipc.h"

#define N1X_ADSP_PCM_BYTES 96U

struct n1x_adsp_pcm_config {
	__u64 address;
	__u32 bytes;
	__u32 rate;
	__u32 channels;
	__u32 sample_bits;
	__u32 period_frames;
	__u32 periods;
	/* Zero preserves the native full-ring default; ALSA starts explicitly. */
	__u32 start_threshold;
	__u8 hardware;
	__u8 memif;
	__u8 irq;
};

struct n1x_adsp_pcm_position {
	__u64 notifications;
	__u32 byte_offset, counter;
	bool valid, at_end;
};

static inline __u64 n1x_adsp_pcm_get64(const __u8 *p)
{
	return (__u64)n1x_adsp_ipc_get32(p) | (__u64)n1x_adsp_ipc_get32(p + 4) << 32;
}

static inline void n1x_adsp_pcm_put64(__u8 *p, __u64 value)
{
	n1x_adsp_ipc_put32(p, value);
	n1x_adsp_ipc_put32(p + 4, value >> 32);
}

/* Encode a primary-playback descriptor, without publishing it. The caller
 * owns the complete address extent and must establish its device-visible
 * mapping, endpoint format support and hardware memif/IRQ assignment.
 * Sample width is the container size in bits, not an ALSA format enum.
 * Hardware and host buffers both use wire memory-type value 1.
 * Errors leave the destination unchanged.
 */
static inline int n1x_adsp_pcm_encode(__u8 *packet, size_t capacity,
				    const struct n1x_adsp_pcm_config *config)
{
	__u8 prepared[N1X_ADSP_PCM_BYTES] = {};
	__u64 frames;
	__u32 frame_bytes;

	if (!packet || !config)
		return -EINVAL;
	if (capacity < sizeof(prepared))
		return -EMSGSIZE;
	if (!config->address || !config->bytes || !config->rate ||
	    !config->channels || config->channels > 2 ||
	    (config->sample_bits != 16 && config->sample_bits != 32) ||
	    !config->period_frames || config->period_frames > 0x7fffffff ||
	    config->periods < 2 || config->periods > 0x7fffffff ||
	    config->hardware > 1 || config->memif > 15 || config->irq > 15 ||
	    (!config->hardware && (config->memif || config->irq)))
		return -EINVAL;
	frame_bytes = config->channels * (config->sample_bits / 8);
	frames = (__u64)config->period_frames * config->periods;
	if (frames > 0xffffffffU / frame_bytes ||
	    config->address > ~(__u64)0 - config->bytes)
		return -ERANGE;
	if (config->bytes != frames * frame_bytes)
		return -EINVAL;
	if (config->start_threshold > frames)
		return -ERANGE;

	n1x_adsp_pcm_put64(prepared, config->address);
	n1x_adsp_pcm_put64(prepared + 8, config->address + config->bytes);
	n1x_adsp_pcm_put64(prepared + 16, config->address);
	n1x_adsp_pcm_put64(prepared + 24, config->address);
	n1x_adsp_pcm_put64(prepared + 32, config->bytes);
	n1x_adsp_ipc_put32(prepared + 48, config->sample_bits);
	n1x_adsp_ipc_put32(prepared + 52, config->rate);
	n1x_adsp_ipc_put32(prepared + 56, config->channels);
	n1x_adsp_ipc_put32(prepared + 60, 1);
	n1x_adsp_ipc_put32(prepared + 64, config->start_threshold ?: frames);
	n1x_adsp_ipc_put32(prepared + 68, 0xffffffff);
	n1x_adsp_ipc_put32(prepared + 72, config->period_frames);
	n1x_adsp_ipc_put32(prepared + 76, config->periods);
	prepared[80] = config->hardware;
	prepared[81] = config->memif;
	prepared[82] = config->irq;
	prepared[83] = 1;
	memcpy(packet, prepared, sizeof(prepared));
	return 0;
}

/* Build a host producer publication after the client has filled its samples.
 * Offsets include the end boundary; preserve that address in the wire record.
 * The owner supplies its last validated read address and next write generation.
 * Availability belongs to the stream client. This neither copies samples nor
 * publishes memory; errors leave the destination unchanged.
 */
static inline int
n1x_adsp_pcm_producer_encode(__u8 *packet, size_t capacity,
			     const struct n1x_adsp_pcm_config *config,
			     __u64 read_address, __u32 write_offset, __u32 counter)
{
	__u8 prepared[N1X_ADSP_PCM_BYTES];
	__u32 frame_bytes;
	int err;

	if (!packet || !config)
		return -EINVAL;
	if (capacity < sizeof(prepared))
		return -EMSGSIZE;
	err = n1x_adsp_pcm_encode(prepared, sizeof(prepared), config);
	if (err)
		return err;
	if (config->hardware)
		return -EINVAL;
	frame_bytes = config->channels * (config->sample_bits / 8);
	if (read_address < config->address || read_address > config->address + config->bytes ||
	    write_offset > config->bytes || counter > 0x7fffffff)
		return -ERANGE;
	if ((read_address - config->address) % frame_bytes || write_offset % frame_bytes)
		return -EINVAL;
	n1x_adsp_pcm_put64(prepared + 16, read_address);
	n1x_adsp_pcm_put64(prepared + 24, config->address + write_offset);
	n1x_adsp_ipc_put32(prepared + 84, counter);
	memcpy(packet, prepared, sizeof(prepared));
	return 0;
}

/* Decode a task-7 playback-consumed notification. Only the read pointer and
 * producer-generation counter are consumed from the inline descriptor.
 * The counter may restart at zero; it is not a count of elapsed periods.
 * Equal pointers can represent another notification after a ring wrap.
 * Errors leave the output unchanged. Outer wrapper lengths are not trusted.
 */
static inline int
n1x_adsp_pcm_consume_decode(struct n1x_adsp_pcm_position *position,
			    const struct n1x_adsp_pcm_position *previous,
			    const struct n1x_adsp_pcm_config *config,
			    const __u8 *packet, size_t bytes)
{
	struct n1x_adsp_ipc_header header;
	struct n1x_adsp_pcm_position next;
	__u64 address, offset;
	__u32 counter, frame_bytes;
	int err;

	if (!position || !previous || !config)
		return -EINVAL;
	err = n1x_adsp_ipc_decode(&header, packet, bytes);
	if (err)
		return err;
	if (header.message_class || header.ack_mode || header.channel != 7 ||
	    header.command != 0x1b)
		return -ENOMSG;
	if (header.parameter2)
		return -EOPNOTSUPP;
	if (header.data_mode != 1 || header.parameter1 < N1X_ADSP_PCM_BYTES ||
	    header.parameter1 > N1X_ADSP_IPC_PAYLOAD_BYTES)
		return -EMSGSIZE;
	if (!config->address || !config->bytes || !config->channels ||
	    config->channels > 2 || (config->sample_bits != 16 && config->sample_bits != 32) ||
	    config->address > ~(__u64)0 - config->bytes)
		return -EINVAL;
	frame_bytes = config->channels * (config->sample_bits / 8);
	if (config->bytes % frame_bytes)
		return -EINVAL;
	address = n1x_adsp_pcm_get64(packet + 0x30);
	counter = n1x_adsp_ipc_get32(packet + 0x74);
	if (address < config->address || address > config->address + config->bytes ||
	    counter > 0x7fffffff)
		return -ERANGE;
	offset = address - config->address;
	if (offset % frame_bytes)
		return -ERANGE;
	if (previous->valid && counter && counter < previous->counter)
		return -ESTALE;
	if (previous->notifications == ~(__u64)0)
		return -EOVERFLOW;
	next = (struct n1x_adsp_pcm_position) {
		.notifications = previous->notifications + 1,
		.byte_offset = offset == config->bytes ? 0 : offset,
		.counter = counter,
		.valid = true,
		.at_end = offset == config->bytes,
	};
	*position = next;
	return 0;
}

#endif
