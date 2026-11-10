// SPDX-License-Identifier: GPL-2.0-only
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>

#include "n1x_adsp_pcm.h"

static const struct n1x_adsp_pcm_config host = {
	.address = 0xe0001000, .bytes = 7680, .rate = 48000, .channels = 2,
	.sample_bits = 16, .period_frames = 480, .periods = 4,
};

static void test_vectors(void)
{
	const __u8 expected_host[N1X_ADSP_PCM_BYTES] = {
		0, 0x10, 0, 0xe0, 0, 0, 0, 0, 0, 0x2e, 0, 0xe0, 0, 0, 0, 0,
		0, 0x10, 0, 0xe0, 0, 0, 0, 0, 0, 0x10, 0, 0xe0, 0, 0, 0, 0,
		0, 0x1e, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
		16, 0, 0, 0, 0x80, 0xbb, 0, 0, 2, 0, 0, 0, 1, 0, 0, 0,
		0x80, 7, 0, 0, 0xff, 0xff, 0xff, 0xff, 0xe0, 1, 0, 0, 4, 0, 0, 0,
		0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
	};
	const __u8 expected_hardware[N1X_ADSP_PCM_BYTES] = {
		0, 0, 0x6c, 0x1a, 0, 0, 0, 0, 0, 0x0f, 0x6c, 0x1a, 0, 0, 0, 0,
		0, 0, 0x6c, 0x1a, 0, 0, 0, 0, 0, 0, 0x6c, 0x1a, 0, 0, 0, 0,
		0, 0x0f, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
		16, 0, 0, 0, 0x80, 0xbb, 0, 0, 2, 0, 0, 0, 1, 0, 0, 0,
		0xc0, 3, 0, 0, 0xff, 0xff, 0xff, 0xff, 0xe0, 1, 0, 0, 2, 0, 0, 0,
		1, 7, 12, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
	};
	struct n1x_adsp_pcm_config hardware = host;
	__u8 packet[N1X_ADSP_PCM_BYTES + 16];

	memset(packet, 0xa5, sizeof(packet));
	assert(!n1x_adsp_pcm_encode(packet, sizeof(packet), &host));
	assert(!memcmp(packet, expected_host, N1X_ADSP_PCM_BYTES));
	for (unsigned int i = N1X_ADSP_PCM_BYTES; i < sizeof(packet); i++)
		assert(packet[i] == 0xa5);
	hardware.address = 0x1a6c0000;
	hardware.bytes = 3840;
	hardware.periods = 2;
	hardware.hardware = 1;
	hardware.memif = 7;
	hardware.irq = 12;
	assert(!n1x_adsp_pcm_encode(packet, sizeof(packet), &hardware));
	assert(!memcmp(packet, expected_hardware, N1X_ADSP_PCM_BYTES));

	/* Container width must remain 32 when only 24 bits are valid. */
	hardware.sample_bits = 32;
	hardware.bytes = 7680;
	assert(!n1x_adsp_pcm_encode(packet, sizeof(packet), &hardware));
	assert(n1x_adsp_ipc_get32(packet + 48) == 32);
	assert(n1x_adsp_ipc_get32(packet + 32) == 7680);
}

static void test_start_policy(void)
{
	struct n1x_adsp_pcm_config config = host;
	__u8 packet[N1X_ADSP_PCM_BYTES], before[N1X_ADSP_PCM_BYTES];
	unsigned int frames = host.period_frames * host.periods;

	/* Windows' default full-ring gate exceeds a partial ALSA prefill. ALSA
	 * already controls START, so the Linux pipeline uses one frame instead.
	 */
	assert(!n1x_adsp_pcm_encode(packet, sizeof(packet), &config));
	assert(n1x_adsp_ipc_get32(packet + 64) > host.period_frames * 2);
	config.start_threshold = 1;
	assert(!n1x_adsp_pcm_encode(packet, sizeof(packet), &config));
	assert(n1x_adsp_ipc_get32(packet + 64) == 1);
	assert(!n1x_adsp_pcm_producer_encode(packet, sizeof(packet), &config,
					  config.address, config.bytes / 2, 0));
	assert(n1x_adsp_ipc_get32(packet + 64) == 1);
	config.hardware = 1;
	assert(!n1x_adsp_pcm_encode(packet, sizeof(packet), &config));
	assert(n1x_adsp_ipc_get32(packet + 64) == 1);
	config.start_threshold = frames;
	assert(!n1x_adsp_pcm_encode(packet, sizeof(packet), &config));
	assert(n1x_adsp_ipc_get32(packet + 64) == frames);
	memcpy(before, packet, sizeof(packet));
	config.start_threshold = frames + 1;
	assert(n1x_adsp_pcm_encode(packet, sizeof(packet), &config) == -ERANGE);
	assert(!memcmp(packet, before, sizeof(packet)));
}

static void test_rejections(void)
{
	__u8 packet[N1X_ADSP_PCM_BYTES], before[N1X_ADSP_PCM_BYTES];

	memset(before, 0xa5, sizeof(before));
	for (unsigned int fault = 0; fault < 23; fault++) {
		struct n1x_adsp_pcm_config config = host;
		int expected = -EINVAL;

		switch (fault) {
		case 0: config.address = 0; break;
		case 1: config.bytes = 0; break;
		case 2: config.rate = 0; break;
		case 3: config.channels = 0; break;
		case 4: config.channels = 3; break;
		case 5: config.sample_bits = 2; break;
		case 6: config.sample_bits = 24; break;
		case 7: config.sample_bits = 0; break;
		case 8: config.period_frames = 0; break;
		case 9: config.period_frames = 0x80000000; break;
		case 10: config.periods = 0; break;
		case 11: config.periods = 1; break;
		case 12: config.periods = 0x80000000; break;
		case 13: config.bytes--; break;
		case 14: config.hardware = 2; break;
		case 15: config.memif = 1; break;
		case 16: config.irq = 1; break;
		case 17:
			config.period_frames = config.periods = 0x7fffffff;
			expected = -ERANGE;
			break;
		case 18:
			config.address = ~(__u64)0 - config.bytes + 1;
			expected = -ERANGE;
			break;
		case 19:
			config.period_frames = 0x7fffffff;
			config.periods = 2;
			expected = -ERANGE;
			break;
		case 20: config.channels = 0xffffffff; break;
		case 21: config.hardware = 1; config.memif = 16; break;
		case 22: config.hardware = 1; config.irq = 16; break;
		}
		memcpy(packet, before, sizeof(packet));
		assert(n1x_adsp_pcm_encode(packet, sizeof(packet), &config) == expected);
		assert(!memcmp(packet, before, sizeof(packet)));
	}
	assert(n1x_adsp_pcm_encode(NULL, sizeof(packet), &host) == -EINVAL);
	assert(n1x_adsp_pcm_encode(packet, sizeof(packet), NULL) == -EINVAL);
	for (size_t size = 0; size < sizeof(packet); size++) {
		__u8 *short_packet = malloc(size ? size : 1);

		assert(short_packet);
		memset(short_packet, 0xa5, size);
		assert(n1x_adsp_pcm_encode(short_packet, size, &host) == -EMSGSIZE);
		for (size_t i = 0; i < size; i++)
			assert(short_packet[i] == 0xa5);
		free(short_packet);
	}
	/* An end-exclusive address at UINT64_MAX is representable. */
	struct n1x_adsp_pcm_config config = host;

	config.address = ~(__u64)0 - config.bytes;
	assert(!n1x_adsp_pcm_encode(packet, sizeof(packet), &config));
	assert(n1x_adsp_ipc_get32(packet + 8) == 0xffffffff);
	assert(n1x_adsp_ipc_get32(packet + 12) == 0xffffffff);
}

static void consume_packet(__u8 *packet, __u64 address, __u32 counter)
{
	memset(packet, 0xa5, N1X_ADSP_IPC_BYTES);
	n1x_adsp_ipc_put32(packet, 0xdeadbeef);
	n1x_adsp_ipc_put32(packet + 4, 0xffffffff);
	packet[18] = 7;
	packet[19] = 0xf;
	packet[20] = 1;
	packet[21] = 0;
	n1x_adsp_ipc_put16(packet + 22, 0x1b);
	n1x_adsp_ipc_put32(packet + 24, 96);
	n1x_adsp_ipc_put32(packet + 28, 0);
	n1x_adsp_pcm_put64(packet + 0x30, address);
	n1x_adsp_ipc_put32(packet + 0x74, counter);
}

static void test_consumed_position(void)
{
	__u8 packet[N1X_ADSP_IPC_BYTES];
	struct n1x_adsp_pcm_position previous = {}, position;

	consume_packet(packet, host.address + 1920, 5);
	assert(!n1x_adsp_pcm_consume_decode(&position, &previous, &host, packet, sizeof(packet)));
	assert(position.valid && !position.at_end && position.byte_offset == 1920 && position.counter == 5 &&
	       position.notifications == 1);
	previous = position;
	assert(!n1x_adsp_pcm_consume_decode(&position, &previous, &host, packet, sizeof(packet)));
	assert(position.notifications == 2 && position.byte_offset == 1920);
	consume_packet(packet, host.address + host.bytes, 0);
	assert(!n1x_adsp_pcm_consume_decode(&position, &previous, &host, packet, sizeof(packet)));
	assert(position.byte_offset == 0 && position.at_end && position.counter == 0);
	n1x_adsp_ipc_put32(packet + 24, 256);
	assert(!n1x_adsp_pcm_consume_decode(&position, &previous, &host, packet, sizeof(packet)));
	consume_packet(packet, host.address, 0x7fffffff);
	assert(!n1x_adsp_pcm_consume_decode(&position, &previous, &host, packet, sizeof(packet)));
	assert(!position.byte_offset && !position.at_end && position.counter == 0x7fffffff);
	/* In-place updates do not change what the decoder reads as prior state. */
	assert(!n1x_adsp_pcm_consume_decode(&position, &position, &host, packet, sizeof(packet)));
	for (unsigned int fault = 0; fault < 19; fault++) {
		struct n1x_adsp_pcm_config config = host;
		struct n1x_adsp_pcm_position before;
		int expected = -EMSGSIZE;

		consume_packet(packet, host.address + 1920, 5);
		memset(&before, 0xa5, sizeof(before));
		position = before;
		previous = (struct n1x_adsp_pcm_position){.valid = true, .counter = 5};
		switch (fault) {
		case 0: packet[18] = 16; expected = -ENOMSG; break;
		case 1: packet[19] = 0x20; expected = -ENOMSG; break;
		case 2: packet[21] = 2; expected = -ENOMSG; break;
		case 3: packet[22] = 0x13; expected = -ENOMSG; break;
		case 4: packet[20] = 0; break;
		case 5: n1x_adsp_ipc_put32(packet + 24, 95); break;
		case 6: n1x_adsp_ipc_put32(packet + 24, 257); break;
		case 7: packet[28] = 1; expected = -EOPNOTSUPP; break;
		case 8: n1x_adsp_pcm_put64(packet + 0x30, host.address - 4); expected = -ERANGE; break;
		case 9: n1x_adsp_pcm_put64(packet + 0x30, host.address + host.bytes + 4); expected = -ERANGE; break;
		case 10: n1x_adsp_pcm_put64(packet + 0x30, host.address + 1); expected = -ERANGE; break;
		case 11: n1x_adsp_ipc_put32(packet + 0x74, 0x80000000); expected = -ERANGE; break;
		case 12: n1x_adsp_ipc_put32(packet + 0x74, 4); expected = -ESTALE; break;
		case 13: previous.notifications = ~(__u64)0; expected = -EOVERFLOW; break;
		case 14: config.bytes--; expected = -EINVAL; break;
		case 15: config.sample_bits = 24; expected = -EINVAL; break;
		case 16: config.channels = 0; expected = -EINVAL; break;
		case 17: config.address = ~(__u64)0 - 4; expected = -EINVAL; break;
		case 18: config.address = 0; expected = -EINVAL; break;
		}
		assert(n1x_adsp_pcm_consume_decode(&position, &previous, &config,
						 packet, sizeof(packet)) == expected);
		assert(!memcmp(&position, &before, sizeof(position)));
	}
	consume_packet(packet, host.address, 0);
	for (size_t bytes = 0; bytes < sizeof(packet); bytes++) {
		__u8 *short_packet = malloc(bytes ? bytes : 1);

		assert(short_packet);
		memcpy(short_packet, packet, bytes);
		assert(n1x_adsp_pcm_consume_decode(&position, &previous, &host,
						 short_packet, bytes) == -EMSGSIZE);
		free(short_packet);
	}
	assert(n1x_adsp_pcm_consume_decode(NULL, &previous, &host, packet, sizeof(packet)) == -EINVAL);
	assert(n1x_adsp_pcm_consume_decode(&position, NULL, &host, packet, sizeof(packet)) == -EINVAL);
	assert(n1x_adsp_pcm_consume_decode(&position, &previous, NULL, packet, sizeof(packet)) == -EINVAL);
	assert(n1x_adsp_pcm_consume_decode(&position, &previous, &host, NULL, sizeof(packet)) == -EINVAL);
}

static void test_producer_publication(void)
{
	const __u8 expected[N1X_ADSP_PCM_BYTES] = {
		0, 0x10, 0, 0xe0, 0, 0, 0, 0, 0, 0x2e, 0, 0xe0, 0, 0, 0, 0,
		0x80, 0x17, 0, 0xe0, 0, 0, 0, 0, 0, 0x1f, 0, 0xe0, 0, 0, 0, 0,
		0, 0x1e, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
		16, 0, 0, 0, 0x80, 0xbb, 0, 0, 2, 0, 0, 0, 1, 0, 0, 0,
		0x80, 7, 0, 0, 0xff, 0xff, 0xff, 0xff, 0xe0, 1, 0, 0, 4, 0, 0, 0,
		0, 0, 0, 1, 9, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
	};
	__u8 packet[N1X_ADSP_PCM_BYTES + 16];

	memset(packet, 0xa5, sizeof(packet));
	assert(!n1x_adsp_pcm_producer_encode(packet, sizeof(packet), &host,
					    0xe0001780, 3840, 9));
	assert(!memcmp(packet, expected, sizeof(expected)));
	for (size_t i = sizeof(expected); i < sizeof(packet); i++)
		assert(packet[i] == 0xa5);
	assert(!n1x_adsp_pcm_producer_encode(packet, sizeof(packet), &host,
					    host.address + host.bytes, host.bytes, 0x7fffffff));
	assert(n1x_adsp_pcm_get64(packet + 16) == host.address + host.bytes);
	assert(n1x_adsp_pcm_get64(packet + 24) == host.address + host.bytes);
	assert(n1x_adsp_ipc_get32(packet + 84) == 0x7fffffff);
	assert(!n1x_adsp_pcm_producer_encode(packet, sizeof(packet), &host, host.address, 0, 0));
	for (unsigned int fault = 0; fault < 12; fault++) {
		struct n1x_adsp_pcm_config config = host;
		__u64 read = host.address;
		__u32 write = 3840, counter = 9;
		__u8 before[sizeof(packet)];
		int err = -ERANGE;

		switch (fault) {
		case 0: read--; break;
		case 1: read += host.bytes + 4; break;
		case 2: write = host.bytes + 4; break;
		case 3: counter = 0x80000000; break;
		case 4: read++; err = -EINVAL; break;
		case 5: write++; err = -EINVAL; break;
		case 6: config.hardware = 1; err = -EINVAL; break;
		case 7: config.bytes--; err = -EINVAL; break;
		case 8: config.rate = 0; err = -EINVAL; break;
		case 9: config.channels = 0; err = -EINVAL; break;
		case 10: config.address = ~(__u64)0 - 4; break;
		case 11: config.sample_bits = 24; err = -EINVAL; break;
		}
		memset(before, 0xa5, sizeof(before));
		memcpy(packet, before, sizeof(packet));
		assert(n1x_adsp_pcm_producer_encode(packet, sizeof(packet), &config,
						   read, write, counter) == err);
		assert(!memcmp(packet, before, sizeof(packet)));
	}
	for (size_t bytes = 0; bytes < N1X_ADSP_PCM_BYTES; bytes++) {
		__u8 *short_packet = malloc(bytes ? bytes : 1);

		assert(short_packet);
		memset(short_packet, 0xa5, bytes);
		assert(n1x_adsp_pcm_producer_encode(short_packet, bytes, &host,
						   host.address, 0, 0) == -EMSGSIZE);
		for (size_t i = 0; i < bytes; i++)
			assert(short_packet[i] == 0xa5);
		free(short_packet);
	}
	assert(n1x_adsp_pcm_producer_encode(NULL, sizeof(packet), &host, host.address, 0, 0) == -EINVAL);
	assert(n1x_adsp_pcm_producer_encode(packet, sizeof(packet), NULL, host.address, 0, 0) == -EINVAL);
}

int main(void)
{
	test_vectors();
	test_start_policy();
	test_rejections();
	test_consumed_position();
	test_producer_publication();
	puts("DSP PCM: descriptor/producer vectors, consumed positions, bounds and generations: PASS");
	return 0;
}
