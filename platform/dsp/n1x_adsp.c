// SPDX-License-Identifier: GPL-2.0-only
/* MT8901 secure boot, IPC and playback driver.
 * Power management adapted from MediaTek's sof/mt8901/mt8901.c:
 * Copyright (c) 2026 MediaTek Inc. (GPL-2.0-only OR BSD-3-Clause).
 */
#include <linux/acpi.h>
#include <linux/atomic.h>
#include <linux/capability.h>
#include <linux/completion.h>
#include <linux/dma-map-ops.h>
#include <linux/dma-mapping.h>
#include <linux/err.h>
#include <linux/firmware.h>
#include <linux/interrupt.h>
#include <linux/io.h>
#include <linux/iopoll.h>
#include <linux/iommu.h>
#include <linux/iommu-dma.h>
#include <linux/kfifo.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/platform_device.h>
#include <linux/pm_runtime.h>
#include <linux/property.h>
#include <linux/slab.h>
#include <linux/soc/mediatek/mtk-pwrap.h>
#include <linux/spinlock.h>
#include <linux/suspend.h>
#include <linux/unaligned.h>
#include <linux/workqueue.h>
#include <sound/soc.h>
#include "n1x_adsp_client.h"
#include "mt8901-afe-sram.h"
#include "n1x_sroot_client.h"
#include "n1x_sroot_firmware.h"

#define ADSP_RX_OFFSET 0x20
#define ADSP_CONFIG_OFFSET 0x3a0
#define ADSP_RX_BYTES 0x120
#define ADSP_TX_OFFSET 0x140
#define ADSP_TX_BUSY 0x14
#define ADSP_IN_SET 0x100
#define ADSP_OUT_STATUS 0x104
#define ADSP_OUT_CLEAR 0x10c
#define ADSP_IPC_TIMEOUT_US 5000000
#define ADSP_PRIMARY_TASK 7
#define ADSP_PROCESSING_TASK 16
#define ADSP_MESSAGE_BYTES 1024U
#define ADSP_PRIMARY_BUFFERS 4U
#define ADSP_PCM_OFFSET (ADSP_PRIMARY_BUFFERS * ADSP_MESSAGE_BYTES)

static bool enable_boot;
module_param(enable_boot, bool, 0400);
MODULE_PARM_DESC(enable_boot, "Permit explicit one-shot secure boot; experimental, disabled by default");

static bool auto_boot;
module_param(auto_boot, bool, 0400);
MODULE_PARM_DESC(auto_boot, "Start enabled DSP firmware at probe for automatic audio integration");

static bool enable_retention_sleep;
module_param(enable_retention_sleep, bool, 0400);
MODULE_PARM_DESC(enable_retention_sleep, "Permit experimental idle-DSP s2idle retention; disabled until hardware qualification");

struct n1x_adsp_target {
	const char *hid, *firmware;
	u32 image_id, dram_bytes;
};

struct n1x_adsp_primary {
	struct device *dev;
	struct n1x_adsp *dsp;
};

static const struct n1x_adsp_target targets[] = {
	{"NVDA8301", "nvidia/n1x/hifi5-0-mt8901-signed.bin",
	 0xc0304, 24U << 20},
	{"NVDA8302", "nvidia/n1x/hifi5-1-mt8901-signed.bin",
	 0xc0305, 24U << 20},
	{"NVDA8303", "nvidia/n1x/hifi1-0-mt8901-signed.bin",
	 0xc0303, 16U << 20},
};

struct n1x_adsp {
	struct device *dev;
	const struct n1x_adsp_target *target;
	const char *firmware;
	void *pwrap, *dram;
	dma_addr_t dma;
	void __iomem *shared, *mailbox;
	struct mutex lock;
	struct completion ready;
	struct completion ipc_done;
	spinlock_t ipc_lock;
	struct n1x_adsp_ipc_reply ipc_reply;
	u16 ipc_token;
	int ipc_error;
	bool ipc_pending, ipc_poisoned;
	bool primary_attempted, primary_ready;
	u8 primary_completed;
	int primary_error;
	struct n1x_adsp_primary *primary_owner;
	bool primary_task_active;
	int primary_task_error;
	bool primary_pcm_attempted, primary_pcm_configured;
	bool primary_pcm_prepared;
	bool primary_start_attempted, primary_running, primary_stopped;
	int primary_pcm_error;
	struct n1x_adsp_pcm_config primary_host_pcm, primary_afe_pcm;
	void (*primary_retire)(struct mt8901_afe_sram_buffer *buffer);
	struct n1x_adsp_pcm_config primary_bridge_pcm;
	struct mt8901_afe_sram_buffer *primary_sram;
	struct mt8901_afe_sram_buffer *processing_messages;
	void __iomem *processing_area;
	u64 processing_address;
	bool processing_active;
	struct n1x_adsp_pcm_position primary_position;
	u64 primary_read_address, primary_write_publications;
	u32 primary_write_offset, primary_write_counter;
	bool primary_period_enabled;
	int primary_period_error;
	void (*primary_period)(void *data, const struct n1x_adsp_pcm_position *position, int error);
	void *primary_period_data;
	struct n1x_sroot_client_result_v2 loader;
	const struct n1x_sroot_client_ops *sroot_ops;
	const struct n1x_sroot_client_sleep_ops *sleep_ops;
	struct n1x_sroot_client *sroot_client;
	struct work_struct power_work;
	spinlock_t power_lock;
	DECLARE_KFIFO(power_requests, u32, 16);
	atomic_t power_queued, power_completed, power_error;
	u32 notifications;
	u16 last_command;
	int error, irq;
	bool attempted, published, boot_ready;
	bool sleep_prepared; /* Protected by lock, like firmware publication. */
	bool sleep_suspended, sleep_irq_disabled;
	bool sleep_pcm, sleep_messages, sleep_draining;
	bool component_registered;
	u32 sleep_cycles;
	int sleep_error;
};

static int n1x_adsp_group_member(struct device *member, void *data)
{
	return member == data ? 0 : -EOPNOTSUPP;
}

static int n1x_adsp_dma_gate(struct device *dev)
{
	struct acpi_device *adev = ACPI_COMPANION(dev);
	struct iommu_domain *domain = iommu_get_domain_for_dev(dev);
	struct iommu_fwspec *spec = dev_iommu_fwspec_get(dev);
	struct iommu_group *group;
	int err;

	if (!adev || !adev->flags.cca_seen || !adev->flags.coherent_dma ||
	    !dev_is_dma_coherent(dev) || !dev->dma_mask || !domain ||
	    !iommu_is_dma_domain(domain) || !use_dma_iommu(dev) ||
	    !spec || spec->num_ids < 1)
		return -EOPNOTSUPP;
	group = iommu_group_get(dev);
	if (!group)
		return -EOPNOTSUPP;
	err = iommu_group_for_each_dev(group, dev, n1x_adsp_group_member);
	iommu_group_put(group);
	return err;
}

static void n1x_adsp_ipc_fail(struct n1x_adsp *dsp, int error)
{
	unsigned long flags;

	spin_lock_irqsave(&dsp->ipc_lock, flags);
	if (!dsp->ipc_poisoned) {
		dsp->ipc_poisoned = true;
		dsp->ipc_error = error;
	}
	if (dsp->ipc_pending) {
		dsp->ipc_pending = false;
		complete(&dsp->ipc_done);
	}
	spin_unlock_irqrestore(&dsp->ipc_lock, flags);
}

static bool n1x_adsp_ipc_receive(struct n1x_adsp *dsp, const u8 *packet)
{
	struct n1x_adsp_ipc_header header;
	unsigned long flags;

	n1x_adsp_ipc_decode(&header, packet, ADSP_RX_BYTES);
	if (header.message_class || header.ack_mode != 2)
		return false;
	spin_lock_irqsave(&dsp->ipc_lock, flags);
	if (!dsp->ipc_poisoned) {
		if (dsp->ipc_pending && n1x_adsp_ipc_ack_matches(&header, dsp->ipc_token)) {
			memcpy(dsp->ipc_reply.packet, packet, ADSP_RX_BYTES);
		} else {
			dsp->ipc_poisoned = true;
			dsp->ipc_error = -EPROTO;
		}
		if (dsp->ipc_pending) {
			dsp->ipc_pending = false;
			complete(&dsp->ipc_done);
		}
	}
	spin_unlock_irqrestore(&dsp->ipc_lock, flags);
	return true;
}

static bool n1x_adsp_tx_idle(struct n1x_adsp *dsp)
{
	return !readl(dsp->shared + ADSP_TX_BUSY) &&
	       !(readl(dsp->mailbox + ADSP_IN_SET) & BIT(0));
}

/* Caller holds dsp->lock. Published boot state owns the power/module lease. */
static int n1x_adsp_transfer_locked(struct n1x_adsp *dsp,
				  const struct n1x_adsp_ipc_request *request,
				  struct n1x_adsp_ipc_reply *reply)
{
	struct n1x_adsp_ipc_request prepared = *request;
	u8 packet[ADSP_RX_BYTES];
	unsigned long flags;
	bool idle;
	int err;

	if (request->token || request->ack_mode != 1)
		return -EINVAL;
	if (dsp->sleep_prepared &&
	    (dsp->sleep_draining || request->command != 0x10 ||
	     (request->channel != ADSP_PRIMARY_TASK && request->channel != ADSP_PROCESSING_TASK)))
		return -EBUSY;
	if (!dsp->published || !dsp->boot_ready || !dsp->loader.accepted || dsp->error)
		return -EHOSTDOWN;
	if (atomic_read(&dsp->power_error))
		return -EHOSTDOWN;
	if (READ_ONCE(dsp->ipc_poisoned))
		return -ENOTRECOVERABLE;
	prepared.token = dsp->ipc_token + 1;
	if (!prepared.token)
		prepared.token = 1;
	err = n1x_adsp_ipc_encode(packet, sizeof(packet), &prepared);
	if (err)
		return err;
	err = read_poll_timeout(n1x_adsp_tx_idle, idle, idle, 1000,
				ADSP_IPC_TIMEOUT_US, false, dsp);
	if (err) {
		n1x_adsp_ipc_fail(dsp, err);
		return err;
	}
	spin_lock_irqsave(&dsp->ipc_lock, flags);
	if (dsp->ipc_poisoned || atomic_read(&dsp->power_error)) {
		err = -ENOTRECOVERABLE;
		goto unlock;
	}
	reinit_completion(&dsp->ipc_done);
	dsp->ipc_token = prepared.token;
	dsp->ipc_pending = true;
	/* Firmware releases TX_BUSY after consuming this SRAM slot. */
	writel(1, dsp->shared + ADSP_TX_BUSY);
	memcpy_toio(dsp->shared + ADSP_TX_OFFSET, packet, sizeof(packet));
	/* Publish the complete SRAM packet before ringing the doorbell. */
	wmb();
	writel(BIT(0), dsp->mailbox + ADSP_IN_SET);
	spin_unlock_irqrestore(&dsp->ipc_lock, flags);
	wait_for_completion_timeout(&dsp->ipc_done,
				    usecs_to_jiffies(ADSP_IPC_TIMEOUT_US));
	spin_lock_irqsave(&dsp->ipc_lock, flags);
	if (dsp->ipc_pending) {
		dsp->ipc_pending = false;
		dsp->ipc_poisoned = true;
		dsp->ipc_error = -ETIMEDOUT;
	}
	err = dsp->ipc_poisoned ? dsp->ipc_error : 0;
	spin_unlock_irqrestore(&dsp->ipc_lock, flags);
	if (err)
		return err;
	/* An ACK completes the request; slot release permits the next request. */
	err = read_poll_timeout(n1x_adsp_tx_idle, idle, idle, 1000,
				ADSP_IPC_TIMEOUT_US, false, dsp);
	if (!err && atomic_read(&dsp->power_error))
		err = -EIO;
	if (err) {
		n1x_adsp_ipc_fail(dsp, err);
		return err;
	}
	spin_lock_irqsave(&dsp->ipc_lock, flags);
	err = dsp->ipc_poisoned ? dsp->ipc_error : 0;
	if (!err)
		*reply = dsp->ipc_reply;
unlock:
	spin_unlock_irqrestore(&dsp->ipc_lock, flags);
	return err;
}

static void n1x_adsp_power_work(struct work_struct *work)
{
	struct n1x_adsp *dsp = container_of(work, struct n1x_adsp, power_work);
	u32 value;
	int err;

	while (!atomic_read(&dsp->power_error) &&
	       kfifo_out_spinlocked(&dsp->power_requests, &value, 1, &dsp->power_lock)) {
		/* Submit the firmware's request through SSPM. This operation can
		 * sleep and must run outside the mailbox interrupt handler.
		 */
		struct power_cntl_scmi_data data = {
			.requestId = 0,
			.customdata = {1, value, 0},
		};
		struct _power_cntrl_request request = {
			.dev = dsp->dev,
			.InBuffer = &data,
			.InBufferSize = sizeof(data),
		};

		err = mtk_send_power_control_req(&request);
		if (err) {
			atomic_cmpxchg(&dsp->power_error, 0, err);
			n1x_adsp_ipc_fail(dsp, err);
			dev_err(dsp->dev, "DSP power request %#x failed: %d\n", value, err);
			return;
		}
		atomic_inc(&dsp->power_completed);
	}
}

static void n1x_adsp_period_receive(struct n1x_adsp *dsp, const u8 *packet)
{
	struct n1x_adsp_pcm_position position;
	void (*period)(void *data, const struct n1x_adsp_pcm_position *position, int error);
	unsigned long flags;
	void *data;
	int err;

	spin_lock_irqsave(&dsp->ipc_lock, flags);
	if (!dsp->primary_period_enabled || dsp->primary_period_error) {
		spin_unlock_irqrestore(&dsp->ipc_lock, flags);
		return;
	}
	if (dsp->ipc_poisoned)
		err = dsp->ipc_error ?: -EPROTO;
	else if (atomic_read(&dsp->power_error))
		err = -EHOSTDOWN;
	else
		err = n1x_adsp_pcm_consume_decode(&position, &dsp->primary_position,
						 &dsp->primary_host_pcm, packet, ADSP_RX_BYTES);
	if (err == -ENOMSG || err == -ESTALE) {
		spin_unlock_irqrestore(&dsp->ipc_lock, flags);
		return;
	}
	if (err) {
		dsp->primary_period_error = err;
		position = dsp->primary_position;
	} else {
		dsp->primary_position = position;
		dsp->primary_read_address = n1x_adsp_pcm_get64(packet + 0x30);
	}
	period = dsp->primary_period;
	data = dsp->primary_period_data;
	spin_unlock_irqrestore(&dsp->ipc_lock, flags);
	/* Detach/close synchronize the IRQ before releasing listener data. */
	if (period)
		period(data, &position, err);
}

static irqreturn_t n1x_adsp_irq(int irq, void *data)
{
	struct n1x_adsp *dsp = data;
	u8 packet[ADSP_RX_BYTES];
	u32 pending, bit, value;
	u16 command;

	if (!READ_ONCE(dsp->published))
		return IRQ_NONE;
	pending = readl(dsp->mailbox + ADSP_OUT_STATUS);
	if (!pending)
		return IRQ_NONE;
	/* Acknowledge the first pending bit before copying the receive slot.
	 * Leave the remaining mailbox bits pending.
	 */
	bit = BIT(__ffs(pending));
	writel(bit, dsp->mailbox + ADSP_OUT_CLEAR);
	memcpy_fromio(packet, dsp->shared + ADSP_RX_OFFSET, sizeof(packet));
	command = get_unaligned_le16(packet + 22);
	WRITE_ONCE(dsp->last_command, command);
	WRITE_ONCE(dsp->notifications, dsp->notifications + 1);
	/* Release the receive slot after copying the complete packet. */
	writel(0, dsp->shared + 0x10);
	if (n1x_adsp_ipc_receive(dsp, packet))
		return IRQ_HANDLED;
	n1x_adsp_period_receive(dsp, packet);
	if ((packet[19] >> 4) == 2 && command == 0xf002) {
		WRITE_ONCE(dsp->boot_ready, true);
		complete(&dsp->ready);
	} else if ((packet[19] >> 4) == 2 && command == 0xf005 &&
		   !atomic_read(&dsp->power_error)) {
		value = get_unaligned_le32(packet + 24);
		if (kfifo_in_spinlocked(&dsp->power_requests, &value, 1, &dsp->power_lock)) {
			atomic_inc(&dsp->power_queued);
			schedule_work(&dsp->power_work);
		} else {
			atomic_cmpxchg(&dsp->power_error, 0, -ENOSPC);
			n1x_adsp_ipc_fail(dsp, -ENOSPC);
			dev_err_ratelimited(dsp->dev, "DSP power request queue overflow\n");
		}
	}
	return IRQ_HANDLED;
}

static int n1x_adsp_boot(struct n1x_adsp *dsp, bool kernel_client)
{
	const struct firmware *firmware;
	u64 end;
	u32 pending, previous_dma, previous_bytes;
	int err;

	if (!enable_boot || (!kernel_client && !capable(CAP_SYS_RAWIO)))
		return -EPERM;
	if (dsp->sleep_prepared)
		return -EBUSY;
	if (dsp->attempted)
		return -EALREADY;
	/* HiFi5-1 shares its control block with HiFi5-0 and requires the
	 * primary core to complete boot first.
	 */
	if (dsp->target->image_id == 0xc0305) {
		struct device *primary = n1x_adsp_find_device(dsp->dev, "NVDA8301");
		struct n1x_adsp *first = NULL;
		bool ready;

		ready = false;
		if (primary) {
			device_lock(primary);
			if (primary->driver && !strcmp(primary->driver->name, "n1x-adsp"))
				first = dev_get_drvdata(primary);
			ready = first && READ_ONCE(first->boot_ready) && READ_ONCE(first->loader.accepted);
			device_unlock(primary);
		}
		put_device(primary);
		if (!ready)
			return -EHOSTDOWN;
	}
	/* Reserve the specific provider before taking power or publishing DMA.
	 * Probe has already established the dependency and held its interface.
	 */
	err = dsp->sroot_ops->prepare(dsp->sroot_client);
	if (err)
		return err;
	err = request_firmware_direct(&firmware, dsp->firmware, dsp->dev);
	if (err)
		goto cancel_provider;
	err = n1x_sroot_validate_image(firmware->data, firmware->size, dsp->target->image_id);
	if (err)
		goto release;
	err = n1x_adsp_dma_gate(dsp->dev);
	if (err)
		goto release;
	err = dma_set_mask_and_coherent(dsp->dev, DMA_BIT_MASK(32));
	if (err)
		goto release;
	err = pm_runtime_resume_and_get(dsp->dev);
	if (err < 0)
		goto release;
	dsp->dram = dma_alloc_coherent(dsp->dev, dsp->target->dram_bytes,
					&dsp->dma, GFP_KERNEL);
	if (!dsp->dram) {
		err = -ENOMEM;
		goto put_pm;
	}
	end = (u64)dsp->dma + dsp->target->dram_bytes - 1;
	if (dsp->dma < 0xe0000000 || end > 0xffffffff || (dsp->dma & 255)) {
		err = -ERANGE;
		goto free;
	}
	/* Powered-down SRAM is not zero-filled. Preserve a pending notification
	 * or a valid DMA-window descriptor without treating arbitrary config
	 * words as a live firmware publication.
	 */
	pending = readl(dsp->mailbox + ADSP_OUT_STATUS);
	previous_dma = readl(dsp->shared + ADSP_CONFIG_OFFSET);
	previous_bytes = readl(dsp->shared + ADSP_CONFIG_OFFSET + 8);
	if (pending || (previous_dma >= 0xe0000000 && !(previous_dma & 255) &&
		       previous_bytes && (u64)previous_dma + previous_bytes <= 0x100000000ULL)) {
		dev_info(dsp->dev, "boot deferred: pending=%#x config0=%#x config8=%#x\n",
			 pending, previous_dma, previous_bytes);
		err = -EBUSY;
		goto free;
	}
	memset(dsp->dram, 0, dsp->target->dram_bytes);
	if (!try_module_get(THIS_MODULE)) {
		err = -ENODEV;
		goto free;
	}
	err = dsp->sroot_ops->publish(dsp->sroot_client);
	if (err) {
		module_put(THIS_MODULE);
		goto free;
	}
	reinit_completion(&dsp->ready);
	dma_wmb();
	/* From this point no failure may free DMA or power down this DSP. */
	dsp->attempted = true;
	WRITE_ONCE(dsp->published, true);
	writel(lower_32_bits(dsp->dma), dsp->shared + ADSP_CONFIG_OFFSET);
	writel(dsp->target->dram_bytes, dsp->shared + ADSP_CONFIG_OFFSET + 8);
	err = dsp->sroot_ops->upload(dsp->sroot_client, dsp->target->image_id,
				    firmware->data, firmware->size, &dsp->loader);
	if (!err && (!dsp->loader.published || !dsp->loader.reply_valid ||
		     !dsp->loader.accepted || !dsp->loader.staging_released ||
		     dsp->loader.reply_header != 0x18))
		err = -EPROTO;
	if (!err && !wait_for_completion_timeout(&dsp->ready, msecs_to_jiffies(30000)))
		err = -ETIMEDOUT;
	dsp->error = err;
	dev_info(dsp->dev,
		"secure boot error=%d accepted=%u ready=%u last_command=%#x; DMA/power retained until reboot\n",
		err, dsp->loader.accepted, dsp->boot_ready, dsp->last_command);
	goto release;
free:
	dma_free_coherent(dsp->dev, dsp->target->dram_bytes, dsp->dram, dsp->dma);
	dsp->dram = NULL;
	dsp->dma = 0;
put_pm:
	pm_runtime_put(dsp->dev);
release:
	release_firmware(firmware);
cancel_provider:
	if (!dsp->published)
		dsp->sroot_ops->cancel(dsp->sroot_client);
	return err;
}

static ssize_t boot_store(struct device *dev, struct device_attribute *attribute,
			 const char *buffer, size_t count)
{
	struct n1x_adsp *dsp = dev_get_drvdata(dev);
	int err;

	if (!sysfs_streq(buffer, "start"))
		return -EINVAL;
	mutex_lock(&dsp->lock);
	err = n1x_adsp_boot(dsp, false);
	if (err && !dsp->attempted)
		dsp->error = err;
	mutex_unlock(&dsp->lock);
	return err ?: count;
}
static DEVICE_ATTR_WO(boot);

static int n1x_adsp_primary_route(struct n1x_adsp *dsp)
{
	static const char * const endpoints[] = {
		"acpi-asd-speaker-subproperties",
		"acpi-asd-headphone-subproperties",
	};
	struct device *asd;
	u32 version, mask, route, selected = 0;
	unsigned int i;
	int err;

	asd = n1x_adsp_find_device(dsp->dev, "NVDA9022");
	if (!asd)
		return -ENODEV;
	err = device_property_read_u32(asd, "acpi-asd-hw-ver", &version);
	if (err)
		goto put;
	err = device_property_read_u32(asd, "acpi-asd-endpoint-list", &mask);
	if (err)
		goto put;
	if (version != 1 || (mask & 5) != 5) {
		err = -EOPNOTSUPP;
		goto put;
	}
	for (i = 0; i < ARRAY_SIZE(endpoints); i++) {
		struct fwnode_handle *node = device_get_named_child_node(asd, endpoints[i]);

		if (!node) {
			err = -ENODEV;
			goto put;
		}
		err = fwnode_property_read_u32(node, "acpi-asd-endpoint-path-config", &route);
		fwnode_handle_put(node);
		if (err)
			goto put;
		if (route != 2 || (selected && selected != route)) {
			err = -EOPNOTSUPP;
			goto put;
		}
		selected = route;
	}
	err = dsp->target->image_id == 0xc0303 ? 0 : -ENODEV;
put:
	put_device(asd);
	return err;
}

/* Caller holds dsp->lock. The boot allocation owns these message-buffer slices. */
static int n1x_adsp_prepare_primary_locked(struct n1x_adsp *dsp)
{
	static const u16 commands[ADSP_PRIMARY_BUFFERS] = {5, 6, 0x20a, 0x20b};
	struct n1x_adsp_ipc_reply reply;
	struct n1x_adsp_ipc_header header;
	struct n1x_adsp_ipc_request request = {
		.channel = ADSP_PRIMARY_TASK,
		.data_mode = 1,
		.ack_mode = 1,
		.parameter1 = 32,
	};
	unsigned int i;
	int err;

	if (dsp->sleep_prepared)
		return -EBUSY;
	if (dsp->primary_attempted && !dsp->primary_ready)
		return dsp->primary_error;
	if (!dsp->published || !dsp->boot_ready || !dsp->loader.accepted || dsp->error)
		return -EHOSTDOWN;
	if (READ_ONCE(dsp->ipc_poisoned) || atomic_read(&dsp->power_error))
		return -ENOTRECOVERABLE;
	if (dsp->primary_ready)
		return 0;
	err = n1x_adsp_primary_route(dsp);
	if (err)
		return err;
	if (!dsp->dram || dsp->target->dram_bytes < ADSP_PRIMARY_BUFFERS * ADSP_MESSAGE_BYTES ||
	    (dsp->dma & 255) || dsp->dma < 0xe0000000 ||
	    dsp->dma > DMA_BIT_MASK(32) - (dsp->target->dram_bytes - 1))
		return -ERANGE;

	/* The primary task uses DRAM, unlike the SRAM-backed tasks 10, 16 and 29. */
	memset(dsp->dram, 0, ADSP_PRIMARY_BUFFERS * ADSP_MESSAGE_BYTES);
	dsp->primary_attempted = true;
	dsp->primary_error = -EINPROGRESS;
	for (i = 0; i < ARRAY_SIZE(commands); i++) {
		unsigned int offset = i * ADSP_MESSAGE_BYTES;
		__le64 payload[4] = {
			cpu_to_le64(dsp->dma + offset),
			cpu_to_le64((unsigned long)(dsp->dram + offset)),
			cpu_to_le64(ADSP_MESSAGE_BYTES),
			0,
		};

		request.command = commands[i];
		request.payload = (const u8 *)payload;
		/* Make the zeroed message memory visible before registering its address. */
		dma_wmb();
		err = n1x_adsp_transfer_locked(dsp, &request, &reply);
		if (err)
			goto failed;
		n1x_adsp_ipc_decode(&header, reply.packet, sizeof(reply.packet));
		if (header.channel != ADSP_PRIMARY_TASK || header.command != commands[i]) {
			err = -EPROTO;
			n1x_adsp_ipc_fail(dsp, err);
			goto failed;
		}
		dsp->primary_completed++;
	}
	if (READ_ONCE(dsp->ipc_poisoned) || atomic_read(&dsp->power_error)) {
		err = -EIO;
		goto failed;
	}
	dsp->primary_ready = true;
	dsp->primary_error = 0;
	return 0;
failed:
	dsp->primary_error = err;
	return err;
}

static ssize_t status_show(struct device *dev, struct device_attribute *attribute, char *buffer)
{
	struct n1x_adsp *dsp = dev_get_drvdata(dev);
	struct n1x_adsp_pcm_position position;
	unsigned long flags;
	u64 write_publications;
	u32 write_offset, write_counter;
	int period_error;
	ssize_t bytes;

	mutex_lock(&dsp->lock);
	spin_lock_irqsave(&dsp->ipc_lock, flags);
	position = dsp->primary_position;
	period_error = dsp->primary_period_error;
	write_publications = dsp->primary_write_publications;
	write_offset = dsp->primary_write_offset;
	write_counter = dsp->primary_write_counter;
	spin_unlock_irqrestore(&dsp->ipc_lock, flags);
	bytes = sysfs_emit(buffer,
		"image=%#x attempted=%u published=%u loader_published=%u loader_accepted=%u loader_staging_released=%u ready=%u error=%d notifications=%u last_command=%#x power_queued=%d power_completed=%d power_error=%d ipc_token=%u ipc_pending=%u ipc_error=%d primary_attempted=%u primary_ready=%u primary_completed=%u primary_error=%d primary_task_active=%u primary_task_error=%d primary_client=%u primary_pcm_attempted=%u primary_pcm_configured=%u primary_pcm_error=%d primary_sram_retained=%u primary_pcm_prepared=%u processing_active=%u processing_messages_retained=%u pcm_notifications=%llu pcm_offset=%u pcm_counter=%u pcm_period_error=%d pcm_write_offset=%u pcm_next_write_counter=%u pcm_write_publications=%llu pcm_start_attempted=%u pcm_running=%u pcm_stopped=%u services=0\n",
		dsp->target->image_id, dsp->attempted, dsp->published, dsp->loader.published,
		dsp->loader.accepted, dsp->loader.staging_released, dsp->boot_ready, dsp->error,
		dsp->notifications, dsp->last_command,
		atomic_read(&dsp->power_queued), atomic_read(&dsp->power_completed),
		atomic_read(&dsp->power_error), dsp->ipc_token,
		READ_ONCE(dsp->ipc_pending), READ_ONCE(dsp->ipc_error),
		dsp->primary_attempted, dsp->primary_ready, dsp->primary_completed, dsp->primary_error,
		dsp->primary_task_active, dsp->primary_task_error, !!dsp->primary_owner,
		dsp->primary_pcm_attempted, dsp->primary_pcm_configured, dsp->primary_pcm_error,
		!!dsp->primary_sram, dsp->primary_pcm_prepared,
		dsp->processing_active, !!dsp->processing_messages, position.notifications,
		position.byte_offset, position.counter, period_error,
		write_offset, write_counter, write_publications,
		dsp->primary_start_attempted, dsp->primary_running, dsp->primary_stopped);
	mutex_unlock(&dsp->lock);
	return bytes;
}
static DEVICE_ATTR_RO(status);

/* Explicit root-only diagnostic, separate from metadata-only status. Reading
 * these mailbox/config words never acknowledges a notification or publishes
 * a DMA window. Access is bracketed by the existing SSPM runtime power path.
 */
static ssize_t inspect_show(struct device *dev, struct device_attribute *attribute, char *buffer)
{
	struct n1x_adsp *dsp = dev_get_drvdata(dev);
	ssize_t bytes;
	int err;

	if (!capable(CAP_SYS_RAWIO))
		return -EPERM;
	mutex_lock(&dsp->lock);
	if (dsp->published || dsp->sleep_prepared) {
		bytes = -EBUSY;
		goto unlock;
	}
	err = pm_runtime_resume_and_get(dev);
	if (err < 0) {
		bytes = err;
		goto unlock;
	}
	bytes = sysfs_emit(buffer, "out=%#x config0=%#x config4=%#x config8=%#x configc=%#x\n",
		readl(dsp->mailbox + ADSP_OUT_STATUS),
		readl(dsp->shared + ADSP_CONFIG_OFFSET),
		readl(dsp->shared + ADSP_CONFIG_OFFSET + 4),
		readl(dsp->shared + ADSP_CONFIG_OFFSET + 8),
		readl(dsp->shared + ADSP_CONFIG_OFFSET + 12));
	pm_runtime_mark_last_busy(dev);
	pm_runtime_put_autosuspend(dev);
unlock:
	mutex_unlock(&dsp->lock);
	return bytes;
}
static struct device_attribute dev_attr_inspect = __ATTR(inspect, 0400, inspect_show, NULL);

static ssize_t sleep_status_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct n1x_adsp *dsp = dev_get_drvdata(dev);
	ssize_t size;

	mutex_lock(&dsp->lock);
	size = sysfs_emit(buf,
			  "enabled=%u prepared=%u suspended=%u irq_disabled=%u cycles=%u error=%d\n",
			 enable_retention_sleep, dsp->sleep_prepared, dsp->sleep_suspended,
			 dsp->sleep_irq_disabled, dsp->sleep_cycles, dsp->sleep_error);
	mutex_unlock(&dsp->lock);
	return size;
}
static DEVICE_ATTR_RO(sleep_status);

static ssize_t asoc_ready_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct n1x_adsp *dsp = dev_get_drvdata(dev);
	ssize_t size;

	mutex_lock(&dsp->lock);
	size = sysfs_emit(buf, "%u\n", dsp->component_registered && dsp->boot_ready && !dsp->error);
	mutex_unlock(&dsp->lock);
	return size;
}
static DEVICE_ATTR_RO(asoc_ready);

static struct attribute *n1x_adsp_attrs[] = {
	&dev_attr_boot.attr, &dev_attr_status.attr, &dev_attr_inspect.attr,
	&dev_attr_sleep_status.attr, &dev_attr_asoc_ready.attr, NULL
};
ATTRIBUTE_GROUPS(n1x_adsp);

static void n1x_adsp_put_provider(void *data)
{
	struct n1x_adsp *dsp = data;

	/* Published handles deliberately retain their provider lifetime. */
	dsp->sroot_ops->put(dsp->sroot_client);
	symbol_put(n1x_sroot_client_ops_v4);
}

static int n1x_adsp_get_provider(struct n1x_adsp *dsp)
{
	typeof(n1x_sroot_client_ops_v4) *get_ops;

	get_ops = symbol_get(n1x_sroot_client_ops_v4);
	if (!get_ops)
		return -EPROBE_DEFER;
	dsp->sleep_ops = get_ops();
	dsp->sroot_ops = dsp->sleep_ops->client;
	dsp->sroot_client = dsp->sroot_ops->get(dsp->dev);
	if (IS_ERR(dsp->sroot_client)) {
		int err = PTR_ERR(dsp->sroot_client);

		symbol_put(n1x_sroot_client_ops_v4);
		return err;
	}
	return devm_add_action_or_reset(dsp->dev, n1x_adsp_put_provider, dsp);
}

static void n1x_adsp_del_link(void *data)
{
	device_link_del(data);
}

static int n1x_adsp_link_primary(struct n1x_adsp *dsp)
{
	struct device_link *link;
	struct device *primary;

	if (dsp->target->image_id != 0xc0305)
		return 0;
	primary = n1x_adsp_find_device(dsp->dev, "NVDA8301");
	if (!primary)
		return -EPROBE_DEFER;
	/* HiFi5-1 shares control hardware with HiFi5-0: secondary suspends first
	 * and resumes last. No runtime-PM reference is released by this link.
	 */
	link = device_link_add(dsp->dev, primary, DL_FLAG_STATELESS);
	put_device(primary);
	if (!link)
		return -ENOMEM;
	return devm_add_action_or_reset(dsp->dev, n1x_adsp_del_link, link);
}

static int n1x_adsp_link_afe(struct n1x_adsp *dsp)
{
	struct device_link *link;
	struct device *afe;

	afe = n1x_adsp_find_device(dsp->dev, "NVDA9022");
	if (!afe)
		return -EPROBE_DEFER;
	link = device_link_add(dsp->dev, afe, DL_FLAG_STATELESS);
	put_device(afe);
	if (!link)
		return -ENOMEM;
	return devm_add_action_or_reset(dsp->dev, n1x_adsp_del_link, link);
}

static const struct snd_soc_component_driver n1x_adsp_component = {
	.name = "n1x-adsp",
};

static int n1x_adsp_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct acpi_device *adev = ACPI_COMPANION(dev);
	struct acpi_buffer path = {ACPI_ALLOCATE_BUFFER, NULL};
	struct resource *config, *shared, *mailbox, tail;
	struct n1x_adsp *dsp;
	unsigned int i;
	int irq, err;

	if (!adev)
		return -ENODEV;
	for (i = 0; i < ARRAY_SIZE(targets); i++)
		if (!strcmp(acpi_device_hid(adev), targets[i].hid))
			break;
	if (i == ARRAY_SIZE(targets))
		return -ENODEV;
	config = platform_get_resource(pdev, IORESOURCE_MEM, 0);
	shared = platform_get_resource(pdev, IORESOURCE_MEM, 4);
	mailbox = platform_get_resource(pdev, IORESOURCE_MEM, 5);
	if (!config || !shared || !mailbox || resource_size(config) < sizeof(u32) ||
	    resource_size(shared) < 0x400 ||
	    resource_size(mailbox) < ADSP_OUT_CLEAR + sizeof(u32))
		return -ENODEV;
	dsp = devm_kzalloc(dev, sizeof(*dsp), GFP_KERNEL);
	if (!dsp)
		return -ENOMEM;
	dsp->dev = dev;
	dsp->target = &targets[i];
	dsp->firmware = dsp->target->firmware;
	err = n1x_adsp_get_provider(dsp);
	if (err)
		return dev_err_probe(dev, err, "no unique ready SROOT provider\n");
	err = n1x_adsp_link_primary(dsp);
	if (err)
		return dev_err_probe(dev, err, "no HiFi5 primary PM dependency\n");
	err = n1x_adsp_link_afe(dsp);
	if (err)
		return dev_err_probe(dev, err, "no unique AFE power supplier\n");
	device_property_read_string(dev, "firmware-name", &dsp->firmware);
	mutex_init(&dsp->lock);
	init_completion(&dsp->ready);
	init_completion(&dsp->ipc_done);
	spin_lock_init(&dsp->ipc_lock);
	INIT_WORK(&dsp->power_work, n1x_adsp_power_work);
	spin_lock_init(&dsp->power_lock);
	INIT_KFIFO(dsp->power_requests);
	atomic_set(&dsp->power_queued, 0);
	atomic_set(&dsp->power_completed, 0);
	atomic_set(&dsp->power_error, 0);
	tail = *shared;
	tail.start = tail.end + 1 - 0x400;
	dsp->shared = devm_ioremap_resource(dev, &tail);
	if (IS_ERR(dsp->shared))
		return PTR_ERR(dsp->shared);
	dsp->mailbox = devm_platform_ioremap_resource(pdev, 5);
	if (IS_ERR(dsp->mailbox))
		return PTR_ERR(dsp->mailbox);
	irq = platform_get_irq(pdev, 0);
	if (irq < 0)
		return irq;
	err = devm_request_irq(dev, irq, n1x_adsp_irq, 0, dev_name(dev), dsp);
	if (err)
		return err;
	dsp->irq = irq;
	if (ACPI_FAILURE(acpi_get_name(adev->handle, ACPI_FULL_PATHNAME, &path)))
		return -EINVAL;
	dsp->pwrap = mtk_pwrap_dev_probe(path.pointer);
	kfree(path.pointer);
	if (!dsp->pwrap)
		return -ENODEV;
	platform_set_drvdata(pdev, dsp);
	pm_runtime_set_autosuspend_delay(dev, 100);
	pm_runtime_use_autosuspend(dev);
	err = pm_runtime_set_active(dev);
	if (err) {
		pm_runtime_dont_use_autosuspend(dev);
		mtk_pwrap_dev_remove(dsp->pwrap);
		return err;
	}
	pm_runtime_enable(dev);
	pm_runtime_mark_last_busy(dev);
	pm_runtime_idle(dev);
	if (auto_boot) {
		mutex_lock(&dsp->lock);
		err = n1x_adsp_boot(dsp, true);
		mutex_unlock(&dsp->lock);
		/* Never unwind devres after a possible DSP address publication. */
		if (err) {
			dev_err(dev, "automatic DSP boot failed (%d); instance retained\n", err);
		} else {
			err = devm_snd_soc_register_component(dev, &n1x_adsp_component, NULL, 0);
			if (err) {
				dsp->error = err;
				dev_err(dev, "ASoC registration failed (%d); DSP retained\n", err);
			} else {
				dsp->component_registered = true;
			}
		}
		return 0;
	}
	dev_info(dev, "secure-boot experiment available; enable_boot=%u; no firmware started\n", enable_boot);
	return 0;
}

static void n1x_adsp_remove(struct platform_device *pdev)
{
	struct n1x_adsp *dsp = platform_get_drvdata(pdev);
	int err;

	/* Published instances pin the module and suppress manual sysfs unbind. */
	devm_free_irq(&pdev->dev, dsp->irq, dsp);
	cancel_work_sync(&dsp->power_work);
	err = pm_runtime_resume_and_get(&pdev->dev);
	pm_runtime_dont_use_autosuspend(&pdev->dev);
	pm_runtime_disable(&pdev->dev);
	mtk_pwrap_dev_remove(dsp->pwrap);
	if (err >= 0)
		pm_runtime_put_noidle(&pdev->dev);
}

static int n1x_adsp_runtime_suspend(struct device *dev)
{
	struct n1x_adsp *dsp = dev_get_drvdata(dev);

	if (READ_ONCE(dsp->published))
		return -EBUSY;
	return mtk_pwrap_dev_suspend(dsp->pwrap, 0);
}

static int n1x_adsp_runtime_resume(struct device *dev)
{
	struct n1x_adsp *dsp = dev_get_drvdata(dev);

	return mtk_pwrap_dev_resume(dsp->pwrap, 0);
}

static int n1x_adsp_prepare(struct device *dev)
{
	struct n1x_adsp *dsp = dev_get_drvdata(dev);
	int err = 0;

	/* Admission must happen before any device suspends. Retention is not a
	 * shutdown/reclamation contract and cannot support hibernation or deep
	 * sleep. AFE-owned SRAM/tasks are not yet covered by this idle-core path.
	 */
	mutex_lock(&dsp->lock);
	if (dsp->published) {
		if (!enable_retention_sleep || pm_suspend_target_state != PM_SUSPEND_TO_IDLE)
			err = -EOPNOTSUPP;
		else if (!dsp->boot_ready || !dsp->loader.accepted ||
			 !dsp->loader.staging_released || dsp->error || dsp->sleep_error ||
			 READ_ONCE(dsp->ipc_poisoned) || atomic_read(&dsp->power_error))
			err = -ENOTRECOVERABLE;
		else if (!dsp->component_registered &&
			 (dsp->primary_owner || dsp->primary_task_active ||
			  dsp->processing_active ||
			  dsp->primary_sram || dsp->processing_messages))
			err = -EBUSY;
		if (err)
			dev_warn_ratelimited(dev,
					     "DSP retention sleep unavailable (%d)\n", err);
	}
	if (!err)
		dsp->sleep_prepared = true;
	mutex_unlock(&dsp->lock);
	return err;
}

/* The card has stopped streams before this DSP suspends. The AFE owns the
 * retained SRAM snapshot and will not power down until all DSP votes arrive.
 */
static int n1x_adsp_retention_sram(struct n1x_adsp *dsp, bool wake)
{
	typeof(mt8901_afe_sram_suspend) *vote;
	struct mt8901_afe_sram_buffer *buffers[] = {dsp->primary_sram, dsp->processing_messages};
	bool *voted[] = {&dsp->sleep_pcm, &dsp->sleep_messages};
	unsigned int i;
	int err = 0;

	if (!buffers[0] && !buffers[1])
		return 0;
	vote = wake ? symbol_get(mt8901_afe_sram_resume) : symbol_get(mt8901_afe_sram_suspend);
	if (!vote)
		return -EOPNOTSUPP;
	for (i = 0; i < ARRAY_SIZE(buffers); i++) {
		if (!buffers[i] || (wake && !*voted[i]))
			continue;
		err = vote(buffers[i]);
		if (err)
			break;
		*voted[i] = !wake;
	}
	if (wake)
		symbol_put(mt8901_afe_sram_resume);
	else
		symbol_put(mt8901_afe_sram_suspend);
	return err;
}

/* Called with dsp->lock held, only after an acknowledged D3 transition. */
static int n1x_adsp_retention_wake(struct n1x_adsp *dsp, bool voted)
{
	int err;

	/* Check AFE restoration before permitting DSP DMA to its SRAM again. */
	err = n1x_adsp_retention_sram(dsp, true);
	if (!err)
		err = mtk_pwrap_dev_resume(dsp->pwrap, 1);
	if (!err && (readl(dsp->shared + ADSP_CONFIG_OFFSET) != lower_32_bits(dsp->dma) ||
		     readl(dsp->shared + ADSP_CONFIG_OFFSET + 8) != dsp->target->dram_bytes))
		err = -EIO;
	if (!err && voted)
		err = dsp->sleep_ops->resume(dsp->sroot_client);
	if (err) {
		dsp->sleep_error = err;
		dsp->error = err;
		dev_err(dsp->dev, "DSP retention resume failed (%d); DMA/leases retained\n", err);
		return err;
	}
	dsp->sleep_suspended = false;
	dsp->sleep_irq_disabled = false;
	enable_irq(dsp->irq);
	return 0;
}

static int n1x_adsp_suspend(struct device *dev)
{
	struct n1x_adsp *dsp = dev_get_drvdata(dev);
	int err, rollback;

	if (!dsp->published)
		return pm_runtime_force_suspend(dev);
	mutex_lock(&dsp->lock);
	if (!dsp->sleep_prepared || dsp->sleep_suspended || dsp->error || dsp->primary_running) {
		err = -EBUSY;
		goto unlock;
	}
	dsp->sleep_draining = true;
	/* No new host IPC can enter after prepare. Disable/synchronize the IRQ
	 * before flushing so it cannot queue a power request behind the flush.
	 */
	disable_irq(dsp->irq);
	dsp->sleep_irq_disabled = true;
	flush_work(&dsp->power_work);
	if (READ_ONCE(dsp->ipc_poisoned) || atomic_read(&dsp->power_error)) {
		err = -ENOTRECOVERABLE;
		goto enable;
	}
	if (!n1x_adsp_tx_idle(dsp) || readl(dsp->mailbox + ADSP_OUT_STATUS)) {
		err = -EBUSY;
		goto enable;
	}
	/* Windows PEP encodes SystemStateTransition in bit 0. Keep all published
	 * memory, mappings, PM references and module leases across this request.
	 * SET acknowledgment is not used as permission to free DSP memory.
	 */
	err = mtk_pwrap_dev_suspend(dsp->pwrap, 1);
	if (err == -ETIMEDOUT) {
		dsp->sleep_error = err;
		dsp->error = err;
		dev_err(dev, "DSP D3 completion unknown; IRQ disabled, DMA/leases retained\n");
		goto unlock;
	}
	if (err)
		goto enable;
	dsp->sleep_suspended = true;
	err = n1x_adsp_retention_sram(dsp, false);
	if (!err)
		err = dsp->sleep_ops->suspend(dsp->sroot_client);
	if (err) {
		/* The PM core does not resume the device whose suspend failed. */
		rollback = n1x_adsp_retention_wake(dsp, false);
		if (rollback)
			err = rollback;
		goto unlock;
	}
	dev_info(dev, "DSP retained in D3; operating DMA and provider lease kept\n");
	goto unlock;
enable:
	dsp->sleep_irq_disabled = false;
	enable_irq(dsp->irq);
unlock:
	mutex_unlock(&dsp->lock);
	return err;
}

static int n1x_adsp_resume(struct device *dev)
{
	struct n1x_adsp *dsp = dev_get_drvdata(dev);
	int err = 0;

	if (!dsp->published)
		return pm_runtime_force_resume(dev);
	mutex_lock(&dsp->lock);
	if (dsp->sleep_suspended) {
		err = n1x_adsp_retention_wake(dsp, true);
		if (!err) {
			dsp->sleep_cycles++;
			dev_info(dev, "DSP restored to D0; retained cycle %u\n", dsp->sleep_cycles);
		}
	}
	mutex_unlock(&dsp->lock);
	return err;
}

static void n1x_adsp_complete(struct device *dev)
{
	struct n1x_adsp *dsp = dev_get_drvdata(dev);

	/* Also called when another device aborts the power transition. */
	mutex_lock(&dsp->lock);
	dsp->sleep_prepared = false;
	dsp->sleep_draining = false;
	mutex_unlock(&dsp->lock);
}

static const struct dev_pm_ops n1x_adsp_pm = {
	.prepare = pm_sleep_ptr(n1x_adsp_prepare),
	.complete = pm_sleep_ptr(n1x_adsp_complete),
	SYSTEM_SLEEP_PM_OPS(n1x_adsp_suspend, n1x_adsp_resume)
	RUNTIME_PM_OPS(n1x_adsp_runtime_suspend, n1x_adsp_runtime_resume, NULL)
};

static const struct acpi_device_id n1x_adsp_ids[] = {
	{"NVDA8301"}, {"NVDA8302"}, {"NVDA8303"}, {}
};
MODULE_DEVICE_TABLE(acpi, n1x_adsp_ids);

static struct platform_driver n1x_adsp_driver = {
	.probe = n1x_adsp_probe,
	.remove = n1x_adsp_remove,
	.driver = {
		.name = "n1x-adsp",
		.acpi_match_table = n1x_adsp_ids,
		.pm = pm_ptr(&n1x_adsp_pm),
		.dev_groups = n1x_adsp_groups,
		.suppress_bind_attrs = true,
	}
};

int n1x_adsp_transfer(struct device *dev,
		      const struct n1x_adsp_ipc_request *request,
		      struct n1x_adsp_ipc_reply *reply)
{
	struct n1x_adsp *dsp;
	int err;

	if (!dev || !request || !reply)
		return -EINVAL;
	if (request->channel == ADSP_PRIMARY_TASK || request->channel == ADSP_PROCESSING_TASK)
		return -EOPNOTSUPP;
	device_lock(dev);
	if (dev->driver != &n1x_adsp_driver.driver) {
		err = -ENODEV;
		goto unlock_device;
	}
	dsp = dev_get_drvdata(dev);
	err = mutex_lock_interruptible(&dsp->lock);
	if (err)
		goto unlock_device;
	err = n1x_adsp_transfer_locked(dsp, request, reply);
	mutex_unlock(&dsp->lock);
unlock_device:
	device_unlock(dev);
	return err;
}
EXPORT_SYMBOL_GPL(n1x_adsp_transfer);

int n1x_adsp_prepare_primary(struct device *dev)
{
	struct n1x_adsp *dsp;
	int err;

	if (!dev)
		return -EINVAL;
	device_lock(dev);
	if (dev->driver != &n1x_adsp_driver.driver) {
		err = -ENODEV;
		goto unlock_device;
	}
	dsp = dev_get_drvdata(dev);
	err = mutex_lock_interruptible(&dsp->lock);
	if (err)
		goto unlock_device;
	err = n1x_adsp_prepare_primary_locked(dsp);
	mutex_unlock(&dsp->lock);
unlock_device:
	device_unlock(dev);
	return err;
}
EXPORT_SYMBOL_GPL(n1x_adsp_prepare_primary);

/* Caller holds dsp->lock. Transport success also requires the service echo. */
static int n1x_adsp_primary_control(struct n1x_adsp *dsp, u8 channel, u16 command,
				    u32 parameter, u32 parameter2)
{
	struct n1x_adsp_ipc_request request = {
		.channel = channel,
		.ack_mode = 1,
		.command = command,
		.parameter1 = parameter, .parameter2 = parameter2,
	};
	struct n1x_adsp_ipc_header header;
	struct n1x_adsp_ipc_reply reply;
	int err;

	err = n1x_adsp_transfer_locked(dsp, &request, &reply);
	if (err)
		return err;
	n1x_adsp_ipc_decode(&header, reply.packet, sizeof(reply.packet));
	if (header.channel != channel || header.command != command) {
		n1x_adsp_ipc_fail(dsp, -EPROTO);
		return -EPROTO;
	}
	return 0;
}

static int n1x_adsp_primary_command(struct n1x_adsp *dsp, u8 channel, u16 command, u32 parameter)
{
	return n1x_adsp_primary_control(dsp, channel, command, parameter, 0);
}

struct n1x_adsp_primary *n1x_adsp_primary_open(struct device *dev)
{
	struct n1x_adsp_primary *primary = NULL;
	struct n1x_adsp *dsp;
	int err;

	if (!dev)
		return ERR_PTR(-EINVAL);
	device_lock(dev);
	if (dev->driver != &n1x_adsp_driver.driver) {
		err = -ENODEV;
		goto unlock_device;
	}
	dsp = dev_get_drvdata(dev);
	err = mutex_lock_interruptible(&dsp->lock);
	if (err)
		goto unlock_device;
	if (auto_boot && !dsp->attempted) {
		err = n1x_adsp_boot(dsp, true);
		if (err)
			goto unlock;
	}
	if (dsp->primary_task_error) {
		err = dsp->primary_task_error;
		goto unlock;
	}
	if (dsp->primary_owner || dsp->primary_pcm_attempted) {
		err = -EBUSY;
		goto unlock;
	}
	primary = kzalloc(sizeof(*primary), GFP_KERNEL);
	if (!primary) {
		err = -ENOMEM;
		goto unlock;
	}
	err = n1x_adsp_prepare_primary_locked(dsp);
	if (err)
		goto free;
	/* An unsuccessful OPEN can leave the remote task active. */
	dsp->primary_task_active = true;
	err = n1x_adsp_primary_command(dsp, ADSP_PRIMARY_TASK, 1, 0);
	if (err) {
		dsp->primary_task_error = err;
		goto free;
	}
	primary->dev = get_device(dev);
	primary->dsp = dsp;
	dsp->primary_owner = primary;
	goto unlock;
free:
	kfree(primary);
unlock:
	mutex_unlock(&dsp->lock);
unlock_device:
	device_unlock(dev);
	return err ? ERR_PTR(err) : primary;
}
EXPORT_SYMBOL_GPL(n1x_adsp_primary_open);

/* Caller holds dsp->lock; a listener may only use non-sleeping APIs. */
static void n1x_adsp_primary_period_disable(struct n1x_adsp *dsp)
{
	unsigned long flags;

	spin_lock_irqsave(&dsp->ipc_lock, flags);
	dsp->primary_period_enabled = false;
	dsp->primary_period = NULL;
	dsp->primary_period_data = NULL;
	spin_unlock_irqrestore(&dsp->ipc_lock, flags);
	synchronize_irq(dsp->irq);
}

static int n1x_adsp_primary_stop_locked(struct n1x_adsp *dsp);

int n1x_adsp_primary_close(struct n1x_adsp_primary *primary)
{
	struct device *dev;
	struct n1x_adsp *dsp;
	int err;

	if (IS_ERR_OR_NULL(primary))
		return -EINVAL;
	dev = primary->dev;
	device_lock(dev);
	if (dev->driver != &n1x_adsp_driver.driver) {
		err = -ENODEV;
		goto unlock_device;
	}
	dsp = dev_get_drvdata(dev);
	mutex_lock(&dsp->lock);
	if (dsp->primary_owner != primary) {
		err = -EINVAL;
		goto unlock;
	}
	n1x_adsp_primary_period_disable(dsp);
	err = dsp->primary_task_error;
	if (!err && dsp->primary_start_attempted && !dsp->primary_stopped)
		err = n1x_adsp_primary_stop_locked(dsp);
	if (!err)
		err = n1x_adsp_primary_command(dsp, ADSP_PRIMARY_TASK, 9, 0);
	if (!err)
		err = n1x_adsp_primary_command(dsp, ADSP_PRIMARY_TASK, 2, 0);
	if (!err && dsp->processing_active) {
		err = n1x_adsp_primary_command(dsp, ADSP_PROCESSING_TASK, 9, 0);
		if (!err)
			err = n1x_adsp_primary_command(dsp, ADSP_PROCESSING_TASK, 0x202, 1);
		if (!err)
			err = n1x_adsp_primary_command(dsp, ADSP_PROCESSING_TASK, 2, 0);
	}
	if (err)
		dsp->primary_task_error = err;
	else {
		dsp->primary_task_active = false;
		dsp->primary_pcm_attempted = false;
		dsp->primary_pcm_configured = false;
		dsp->primary_pcm_prepared = false;
		dsp->primary_start_attempted = false;
		dsp->primary_running = false;
		dsp->primary_stopped = false;
		dsp->processing_active = false;
	}
	if (dsp->primary_retire) {
		dsp->primary_retire(dsp->primary_sram);
		dsp->primary_retire = NULL;
	}
	dsp->primary_owner = NULL;
unlock:
	mutex_unlock(&dsp->lock);
unlock_device:
	device_unlock(dev);
	put_device(dev);
	kfree(primary);
	return err;
}
EXPORT_SYMBOL_GPL(n1x_adsp_primary_close);

/* Each task's first registered message slice carries its descriptors. */
static int n1x_adsp_primary_descriptor(struct n1x_adsp *dsp, u8 channel, u16 command,
				       const u8 *descriptor)
{
	__le64 address;
	struct n1x_adsp_ipc_request request = {
		.channel = channel, .command = command,
		.data_mode = 1, .ack_mode = 1,
		.parameter1 = sizeof(address), .payload = (const u8 *)&address,
	};
	struct n1x_adsp_ipc_header header;
	struct n1x_adsp_ipc_reply reply;
	int err;

	if (channel == ADSP_PRIMARY_TASK) {
		address = cpu_to_le64(dsp->dma);
		memcpy(dsp->dram, descriptor, N1X_ADSP_PCM_BYTES);
		dma_wmb();
	} else {
		address = cpu_to_le64(dsp->processing_address);
		memcpy_toio(dsp->processing_area, descriptor, N1X_ADSP_PCM_BYTES);
		/* Publish the complete SRAM descriptor before submitting its address. */
		wmb();
	}
	err = n1x_adsp_transfer_locked(dsp, &request, &reply);
	if (err)
		return err;
	n1x_adsp_ipc_decode(&header, reply.packet, sizeof(reply.packet));
	if (header.channel != channel || header.command != command) {
		n1x_adsp_ipc_fail(dsp, -EPROTO);
		return -EPROTO;
	}
	return 0;
}

/* The route-2 playback chain has one SRAM-backed processing task. */
static int n1x_adsp_processing_open(struct n1x_adsp *dsp,
				   struct mt8901_afe_sram_buffer *peer)
{
	typeof(mt8901_afe_sram_reserve_ipc) *reserve = symbol_get(mt8901_afe_sram_reserve_ipc);
	typeof(mt8901_afe_sram_view) *view = symbol_get(mt8901_afe_sram_view);
	typeof(mt8901_afe_sram_publish_ipc) *publish = symbol_get(mt8901_afe_sram_publish_ipc);
	typeof(mt8901_afe_sram_release) *release = symbol_get(mt8901_afe_sram_release);
	typeof(mt8901_afe_sram_allow_retention) *retention;
	struct mt8901_afe_sram_buffer *messages = NULL;
	struct mt8901_afe_sram_view memory;
	struct n1x_adsp_ipc_request request = {
		.channel = ADSP_PROCESSING_TASK, .data_mode = 1, .ack_mode = 1,
		.parameter1 = 32,
	};
	struct n1x_adsp_ipc_reply reply;
	struct n1x_adsp_ipc_header header;
	unsigned int i;
	int err;

	retention = symbol_get(mt8901_afe_sram_allow_retention);
	if (!reserve || !view || !publish || !release || !retention) {
		err = -EOPNOTSUPP;
		goto put;
	}
	if (dsp->processing_messages) {
		if (!dsp->processing_area || dsp->processing_active) {
			err = -EBUSY;
			goto put;
		}
		/* Successful HWFREE/CLOSE retired the stream, not its registered
		 * message memory. Reuse those same retained task-owned slices.
		 */
		dsp->primary_pcm_attempted = true;
		dsp->processing_active = true;
		err = n1x_adsp_primary_command(dsp, ADSP_PROCESSING_TASK, 1, 0);
		goto put;
	}
	messages = reserve(peer, 2 * ADSP_MESSAGE_BYTES);
	if (IS_ERR(messages)) {
		err = PTR_ERR(messages);
		messages = NULL;
		goto put;
	}
	err = view(messages, &memory);
	if (err)
		goto put;
	if (!memory.area || memory.bytes != 2 * ADSP_MESSAGE_BYTES ||
	    !memory.afe_address || (memory.afe_address & 15) ||
	    memory.afe_address > DMA_BIT_MASK(32) ||
	    memory.bytes - 1 > DMA_BIT_MASK(32) - memory.afe_address) {
		err = -ERANGE;
		goto put;
	}
	err = publish(messages);
	if (err)
		goto put;
	/* Registration can publish an address even when its reply is lost. */
	dsp->primary_pcm_attempted = true;
	dsp->processing_messages = messages;
	dsp->processing_area = memory.area;
	dsp->processing_address = memory.afe_address;
	messages = NULL;
	err = retention(dsp->processing_messages);
	if (err)
		goto put;
	for (i = 0; i < 2; i++) {
		unsigned int offset = i * ADSP_MESSAGE_BYTES;
		__le64 payload[4] = {
			cpu_to_le64(memory.afe_address + offset),
			cpu_to_le64((unsigned long)(memory.area + offset)),
			cpu_to_le64(ADSP_MESSAGE_BYTES), 0,
		};

		request.command = 5 + i;
		request.payload = (const u8 *)payload;
		err = n1x_adsp_transfer_locked(dsp, &request, &reply);
		if (err)
			goto put;
		n1x_adsp_ipc_decode(&header, reply.packet, sizeof(reply.packet));
		if (header.channel != ADSP_PROCESSING_TASK || header.command != request.command) {
			err = -EPROTO;
			n1x_adsp_ipc_fail(dsp, err);
			goto put;
		}
	}
	dsp->processing_active = true;
	err = n1x_adsp_primary_command(dsp, ADSP_PROCESSING_TASK, 1, 0);
put:
	if (messages)
		release(messages);
	if (retention)
		symbol_put(mt8901_afe_sram_allow_retention);
	if (release)
		symbol_put(mt8901_afe_sram_release);
	if (publish)
		symbol_put(mt8901_afe_sram_publish_ipc);
	if (view)
		symbol_put(mt8901_afe_sram_view);
	if (reserve)
		symbol_put(mt8901_afe_sram_reserve_ipc);
	return err;
}

int n1x_adsp_primary_configure(struct n1x_adsp_primary *primary,
			       const struct n1x_adsp_primary_pcm_params *params,
			       struct mt8901_afe_sram_buffer **sram)
{
	typeof(mt8901_afe_sram_endpoint) *endpoint;
	typeof(mt8901_afe_sram_publish) *publish;
	typeof(mt8901_afe_sram_prepare) *prepare;
	typeof(mt8901_afe_sram_prepare_irq) *prepare_irq;
	typeof(mt8901_afe_sram_stop_irq) *stop_irq;
	typeof(mt8901_afe_sram_retire) *retire;
	typeof(mt8901_afe_sram_allow_retention) *retention;
	struct mt8901_afe_sram_endpoint afe;
	struct mt8901_afe_sram_buffer *buffer;
	bool retained;
	struct n1x_adsp_pcm_config host, hardware, bridge;
	u8 host_packet[N1X_ADSP_PCM_BYTES], afe_packet[N1X_ADSP_PCM_BYTES];
	u8 bridge_packet[N1X_ADSP_PCM_BYTES];
	struct n1x_adsp *dsp;
	struct device *dev;
	u64 frames, bytes;
	int err;

	if (IS_ERR_OR_NULL(primary) || !params || !sram || IS_ERR(*sram))
		return -EINVAL;
	endpoint = symbol_get(mt8901_afe_sram_endpoint);
	publish = symbol_get(mt8901_afe_sram_publish);
	prepare = symbol_get(mt8901_afe_sram_prepare);
	prepare_irq = symbol_get(mt8901_afe_sram_prepare_irq);
	stop_irq = symbol_get(mt8901_afe_sram_stop_irq);
	retire = symbol_get(mt8901_afe_sram_retire);
	retention = symbol_get(mt8901_afe_sram_allow_retention);
	if (!endpoint || !publish || !prepare || !prepare_irq ||
	    !stop_irq || !retire || !retention) {
		err = -EOPNOTSUPP;
		goto put;
	}
	dev = primary->dev;
	device_lock(dev);
	if (dev->driver != &n1x_adsp_driver.driver) {
		err = -ENODEV;
		goto unlock_device;
	}
	dsp = dev_get_drvdata(dev);
	err = mutex_lock_interruptible(&dsp->lock);
	if (err)
		goto unlock_device;
	if (dsp->sleep_prepared) {
		err = -EBUSY;
		goto unlock;
	}
	if (dsp->primary_owner != primary || !dsp->primary_task_active) {
		err = -EINVAL;
		goto unlock;
	}
	if (dsp->primary_task_error) {
		err = dsp->primary_task_error;
		goto unlock;
	}
	if (dsp->primary_pcm_attempted) {
		err = -EALREADY;
		goto unlock;
	}
	retained = !*sram;
	buffer = retained ? dsp->primary_sram : *sram;
	if (!buffer) {
		err = -ENOENT;
		goto unlock;
	}
	err = endpoint(buffer, &afe, sizeof(afe));
	if (err)
		goto unlock;
	if (afe.abi_version != 2 || afe.published != retained || !afe.memory.area ||
	    afe.memory.bytes > 0xffffffffU) {
		err = -EINVAL;
		goto unlock;
	}
	if (params->rate != afe.rate || params->channels != afe.channels ||
	    params->sample_bits != afe.sample_bits) {
		err = -EOPNOTSUPP;
		goto unlock;
	}
	if (!params->channels || params->channels > 2 ||
	    (params->sample_bits != 16 && params->sample_bits != 32)) {
		err = -EINVAL;
		goto unlock;
	}
	frames = (u64)params->period_frames * params->periods;
	if (frames > 0xffffffffU / (params->channels * (params->sample_bits / 8))) {
		err = -ERANGE;
		goto unlock;
	}
	bytes = frames * params->channels * (params->sample_bits / 8);
	if (dsp->target->image_id != 0xc0303) {
		err = -EOPNOTSUPP;
		goto unlock;
	}
	if (!dsp->dram || dsp->target->dram_bytes < ADSP_PCM_OFFSET ||
	    bytes > dsp->target->dram_bytes - ADSP_PCM_OFFSET) {
		err = -ERANGE;
		goto unlock;
	}
	host = (struct n1x_adsp_pcm_config){
		.address = dsp->dma + ADSP_PCM_OFFSET, .bytes = bytes,
		.rate = params->rate, .channels = params->channels,
		.sample_bits = params->sample_bits,
		.period_frames = params->period_frames, .periods = params->periods,
	};
	hardware = (struct n1x_adsp_pcm_config){
		.address = dsp->target->image_id == 0xc0303 ? afe.memory.afe_address : afe.memory.dsp_address,
		.bytes = afe.memory.bytes, .rate = afe.rate, .channels = afe.channels,
		.sample_bits = afe.sample_bits, .period_frames = afe.period_frames,
		.periods = afe.periods, .hardware = 1, .memif = afe.memif, .irq = afe.irq,
	};
	err = n1x_adsp_pcm_encode(host_packet, sizeof(host_packet), &host);
	if (!err)
		err = n1x_adsp_pcm_encode(afe_packet, sizeof(afe_packet), &hardware);
	bridge = hardware;
	bridge.hardware = bridge.memif = bridge.irq = 0;
	if (!err)
		err = n1x_adsp_pcm_encode(bridge_packet, sizeof(bridge_packet), &bridge);
	if (err)
		goto unlock;
	err = n1x_adsp_processing_open(dsp, buffer);
	if (err) {
		if (dsp->primary_pcm_attempted)
			goto failed;
		goto unlock;
	}
	memset(dsp->dram + ADSP_PCM_OFFSET, 0, host.bytes);
	dsp->primary_host_pcm = host;
	dsp->primary_afe_pcm = hardware;
	dsp->primary_bridge_pcm = bridge;
	dsp->primary_pcm_attempted = true;
	err = n1x_adsp_primary_descriptor(dsp, ADSP_PRIMARY_TASK, 4, host_packet);
	if (err)
		goto failed;
	err = retained ? 0 : publish(buffer);
	if (err)
		goto failed;
	dsp->primary_sram = buffer;
	/* The published lease pins its owner module after the lookup reference. */
	dsp->primary_retire = retire;
	*sram = NULL;
	err = retention(buffer);
	if (err)
		goto failed;
	err = n1x_adsp_primary_descriptor(dsp, ADSP_PROCESSING_TASK, 0x201, afe_packet);
	if (!err)
		err = n1x_adsp_primary_descriptor(dsp, ADSP_PROCESSING_TASK, 4, bridge_packet);
	if (err)
		goto failed;
	if (READ_ONCE(dsp->ipc_poisoned) || atomic_read(&dsp->power_error)) {
		err = -EIO;
		goto failed;
	}
	dsp->primary_pcm_configured = true;
	goto unlock;
failed:
	dsp->primary_pcm_error = err;
	dsp->primary_task_error = err;
unlock:
	mutex_unlock(&dsp->lock);
unlock_device:
	device_unlock(dev);
put:
	if (retention)
		symbol_put(mt8901_afe_sram_allow_retention);
	if (retire)
		symbol_put(mt8901_afe_sram_retire);
	if (stop_irq)
		symbol_put(mt8901_afe_sram_stop_irq);
	if (prepare_irq)
		symbol_put(mt8901_afe_sram_prepare_irq);
	if (prepare)
		symbol_put(mt8901_afe_sram_prepare);
	if (publish)
		symbol_put(mt8901_afe_sram_publish);
	if (endpoint)
		symbol_put(mt8901_afe_sram_endpoint);
	return err;
}
EXPORT_SYMBOL_GPL(n1x_adsp_primary_configure);

int n1x_adsp_primary_rebind(struct n1x_adsp_primary *primary,
			    struct snd_pcm_substream *substream)
{
	typeof(mt8901_afe_sram_rebind) *rebind;
	typeof(mt8901_afe_sram_retire) *retire;
	struct n1x_adsp *dsp;
	struct device *dev;
	int err;

	if (IS_ERR_OR_NULL(primary) || !substream)
		return -EINVAL;
	rebind = symbol_get(mt8901_afe_sram_rebind);
	retire = symbol_get(mt8901_afe_sram_retire);
	if (!rebind || !retire) {
		err = -EOPNOTSUPP;
		goto put;
	}
	dev = primary->dev;
	device_lock(dev);
	if (dev->driver != &n1x_adsp_driver.driver) {
		err = -ENODEV;
		goto unlock_device;
	}
	dsp = dev_get_drvdata(dev);
	mutex_lock(&dsp->lock);
	if (dsp->primary_owner != primary || !dsp->primary_task_active ||
	    dsp->primary_pcm_attempted || dsp->sleep_prepared) {
		err = -EBUSY;
	} else if (dsp->primary_task_error || dsp->error) {
		err = -ENOTRECOVERABLE;
	} else if (!dsp->primary_sram) {
		err = -ENOENT;
	} else {
		err = rebind(dsp->primary_sram, substream);
		if (!err)
			dsp->primary_retire = retire;
	}
	mutex_unlock(&dsp->lock);
unlock_device:
	device_unlock(dev);
put:
	if (retire)
		symbol_put(mt8901_afe_sram_retire);
	if (rebind)
		symbol_put(mt8901_afe_sram_rebind);
	return err;
}
EXPORT_SYMBOL_GPL(n1x_adsp_primary_rebind);

int n1x_adsp_primary_prepare_pcm(struct n1x_adsp_primary *primary)
{
	typeof(mt8901_afe_sram_endpoint) *endpoint;
	typeof(mt8901_afe_sram_prepare) *prepare;
	typeof(mt8901_afe_sram_prepare_irq) *prepare_irq;
	struct mt8901_afe_sram_endpoint afe;
	u8 host_packet[N1X_ADSP_PCM_BYTES], afe_packet[N1X_ADSP_PCM_BYTES];
	u8 bridge_packet[N1X_ADSP_PCM_BYTES];
	struct n1x_adsp *dsp;
	struct device *dev;
	int err;

	if (IS_ERR_OR_NULL(primary))
		return -EINVAL;
	endpoint = symbol_get(mt8901_afe_sram_endpoint);
	prepare = symbol_get(mt8901_afe_sram_prepare);
	prepare_irq = symbol_get(mt8901_afe_sram_prepare_irq);
	if (!endpoint || !prepare || !prepare_irq) {
		err = -EOPNOTSUPP;
		goto put;
	}
	dev = primary->dev;
	device_lock(dev);
	if (dev->driver != &n1x_adsp_driver.driver) {
		err = -ENODEV;
		goto unlock_device;
	}
	dsp = dev_get_drvdata(dev);
	err = mutex_lock_interruptible(&dsp->lock);
	if (err)
		goto unlock_device;
	if (dsp->sleep_prepared) {
		err = -EBUSY;
		goto unlock;
	}
	if (dsp->primary_owner != primary || !dsp->primary_task_active ||
	    !dsp->primary_pcm_configured || !dsp->primary_sram ||
	    !dsp->processing_active || !dsp->processing_messages || !dsp->processing_area) {
		err = -EINVAL;
		goto unlock;
	}
	if (dsp->primary_task_error) {
		err = dsp->primary_task_error;
		goto unlock;
	}
	if (READ_ONCE(dsp->ipc_poisoned) || atomic_read(&dsp->power_error)) {
		err = -ENOTRECOVERABLE;
		goto unlock;
	}
	err = endpoint(dsp->primary_sram, &afe, sizeof(afe));
	if (err)
		goto unlock;
	if (afe.abi_version != 2 || !afe.published) {
		err = -EINVAL;
		goto unlock;
	}
	if (dsp->primary_pcm_prepared) {
		err = READ_ONCE(dsp->primary_period_error);
		goto unlock;
	}
	/* Task 7 uses its host descriptor for both prepare commands. */
	err = n1x_adsp_pcm_encode(host_packet, sizeof(host_packet), &dsp->primary_host_pcm);
	if (!err)
		err = n1x_adsp_pcm_encode(afe_packet, sizeof(afe_packet), &dsp->primary_afe_pcm);
	if (!err)
		err = n1x_adsp_pcm_encode(bridge_packet, sizeof(bridge_packet), &dsp->primary_bridge_pcm);
	if (err)
		goto unlock;
	err = prepare(dsp->primary_sram);
	if (!err)
		err = n1x_adsp_primary_descriptor(dsp, ADSP_PROCESSING_TASK, 0x203, afe_packet);
	if (!err)
		err = n1x_adsp_primary_descriptor(dsp, ADSP_PROCESSING_TASK, 3, bridge_packet);
	if (!err)
		err = n1x_adsp_primary_descriptor(dsp, ADSP_PRIMARY_TASK, 0x203, host_packet);
	if (!err)
		err = n1x_adsp_primary_descriptor(dsp, ADSP_PRIMARY_TASK, 3, host_packet);
	if (!err && (READ_ONCE(dsp->ipc_poisoned) || atomic_read(&dsp->power_error)))
		err = -EIO;
	if (!err)
		err = prepare_irq(dsp->primary_sram);
	if (!err && (READ_ONCE(dsp->ipc_poisoned) || atomic_read(&dsp->power_error)))
		err = -EIO;
	if (err) {
		dsp->primary_pcm_error = err;
		dsp->primary_task_error = err;
	} else {
		unsigned long flags;

		dsp->primary_pcm_prepared = true;
		dsp->primary_stopped = false;
		dsp->primary_start_attempted = false;
		spin_lock_irqsave(&dsp->ipc_lock, flags);
		dsp->primary_position = (struct n1x_adsp_pcm_position){};
		dsp->primary_read_address = dsp->primary_host_pcm.address;
		dsp->primary_write_offset = 0;
		dsp->primary_write_counter = 0;
		dsp->primary_write_publications = 0;
		dsp->primary_period_error = 0;
		dsp->primary_period_enabled = true;
		spin_unlock_irqrestore(&dsp->ipc_lock, flags);
	}
unlock:
	mutex_unlock(&dsp->lock);
unlock_device:
	device_unlock(dev);
put:
	if (prepare_irq)
		symbol_put(mt8901_afe_sram_prepare_irq);
	if (prepare)
		symbol_put(mt8901_afe_sram_prepare);
	if (endpoint)
		symbol_put(mt8901_afe_sram_endpoint);
	return err;
}
EXPORT_SYMBOL_GPL(n1x_adsp_primary_prepare_pcm);

int n1x_adsp_primary_pcm_view(struct n1x_adsp_primary *primary,
			      struct n1x_adsp_primary_pcm_view *view)
{
	struct n1x_adsp *dsp;
	struct device *dev;
	int err;

	if (IS_ERR_OR_NULL(primary) || !view)
		return -EINVAL;
	dev = primary->dev;
	device_lock(dev);
	if (dev->driver != &n1x_adsp_driver.driver) {
		err = -ENODEV;
		goto unlock_device;
	}
	dsp = dev_get_drvdata(dev);
	mutex_lock(&dsp->lock);
	if (dsp->primary_owner != primary)
		err = -EINVAL;
	else if (dsp->primary_task_error)
		err = dsp->primary_task_error;
	else if (!dsp->primary_pcm_configured)
		err = -EINVAL;
	else if (READ_ONCE(dsp->ipc_poisoned) || atomic_read(&dsp->power_error))
		err = -ENOTRECOVERABLE;
	else {
		view->area = dsp->dram + ADSP_PCM_OFFSET;
		view->bytes = dsp->primary_host_pcm.bytes;
		err = 0;
	}
	mutex_unlock(&dsp->lock);
unlock_device:
	device_unlock(dev);
	return err;
}
EXPORT_SYMBOL_GPL(n1x_adsp_primary_pcm_view);

/* Caller holds dsp->lock. Task STOP does not establish DMA quiescence. */
static int n1x_adsp_primary_stop_locked(struct n1x_adsp *dsp)
{
	typeof(mt8901_afe_sram_stop_irq) *stop_irq;
	int err;

	if (dsp->primary_task_error)
		return dsp->primary_task_error;
	if (dsp->primary_stopped)
		return 0;
	if (!dsp->primary_running)
		return -EINVAL;
	stop_irq = symbol_get(mt8901_afe_sram_stop_irq);
	if (!stop_irq)
		return -EOPNOTSUPP;
	err = n1x_adsp_primary_command(dsp, ADSP_PRIMARY_TASK, 0x10, 0);
	if (!err && (READ_ONCE(dsp->ipc_poisoned) || atomic_read(&dsp->power_error)))
		err = -EIO;
	if (!err)
		err = n1x_adsp_primary_command(dsp, ADSP_PROCESSING_TASK, 0x10, 0);
	if (!err && (READ_ONCE(dsp->ipc_poisoned) || atomic_read(&dsp->power_error)))
		err = -EIO;
	if (!err)
		err = stop_irq(dsp->primary_sram, 3);
	if (!err && (READ_ONCE(dsp->ipc_poisoned) || atomic_read(&dsp->power_error)))
		err = -EIO;
	if (err) {
		dsp->primary_pcm_error = err;
		dsp->primary_task_error = err;
	} else {
		dsp->primary_running = false;
		dsp->primary_stopped = true;
		dsp->primary_pcm_prepared = false;
		n1x_adsp_primary_period_disable(dsp);
	}
	symbol_put(mt8901_afe_sram_stop_irq);
	return err;
}

static int n1x_adsp_primary_trigger(struct n1x_adsp_primary *primary, bool start)
{
	typeof(mt8901_afe_sram_endpoint) *endpoint = NULL;
	struct mt8901_afe_sram_endpoint afe;
	struct n1x_adsp *dsp;
	struct device *dev;
	int err;

	if (IS_ERR_OR_NULL(primary))
		return -EINVAL;
	if (start) {
		endpoint = symbol_get(mt8901_afe_sram_endpoint);
		if (!endpoint)
			return -EOPNOTSUPP;
	}
	dev = primary->dev;
	device_lock(dev);
	if (dev->driver != &n1x_adsp_driver.driver) {
		err = -ENODEV;
		goto unlock_device;
	}
	dsp = dev_get_drvdata(dev);
	err = mutex_lock_interruptible(&dsp->lock);
	if (err)
		goto unlock_device;
	if (start && dsp->sleep_prepared) {
		err = -EBUSY;
		goto unlock;
	}
	if (dsp->primary_owner != primary || !dsp->primary_task_active ||
	    (start && !dsp->primary_pcm_prepared) || !dsp->processing_active ||
	    !dsp->primary_sram) {
		err = -EINVAL;
		goto unlock;
	}
	if (dsp->primary_task_error) {
		err = dsp->primary_task_error;
		goto unlock;
	}
	if (READ_ONCE(dsp->ipc_poisoned) || atomic_read(&dsp->power_error)) {
		err = -ENOTRECOVERABLE;
		goto unlock;
	}
	if (!start) {
		err = n1x_adsp_primary_stop_locked(dsp);
		goto unlock;
	}
	err = READ_ONCE(dsp->primary_period_error);
	if (err)
		goto unlock;
	if (dsp->primary_stopped) {
		err = -EALREADY;
		goto unlock;
	}
	if (dsp->primary_running)
		goto unlock;
	if (dsp->primary_start_attempted) {
		err = -EALREADY;
		goto unlock;
	}
	if (!dsp->primary_write_publications || !READ_ONCE(dsp->primary_period_enabled)) {
		err = -ENODATA;
		goto unlock;
	}
	err = endpoint(dsp->primary_sram, &afe, sizeof(afe));
	if (err)
		goto unlock;
	if (afe.abi_version != 2 || !afe.published || !afe.irq_prepared ||
	    afe.memory.afe_address != dsp->primary_afe_pcm.address ||
	    afe.memory.bytes != dsp->primary_afe_pcm.bytes ||
	    afe.memif != dsp->primary_afe_pcm.memif || afe.irq != dsp->primary_afe_pcm.irq ||
	    afe.rate != dsp->primary_afe_pcm.rate || afe.channels != dsp->primary_afe_pcm.channels ||
	    afe.sample_bits != dsp->primary_afe_pcm.sample_bits ||
	    afe.period_frames != dsp->primary_afe_pcm.period_frames ||
	    afe.periods != dsp->primary_afe_pcm.periods) {
		err = -EINVAL;
		goto unlock;
	}
	/* Route-2 normal playback mode 0; routing is owned by the Linux audio client. */
	dsp->primary_start_attempted = true;
	err = n1x_adsp_primary_control(dsp, ADSP_PROCESSING_TASK, 0x0f, 0, 0);
	if (!err && (READ_ONCE(dsp->ipc_poisoned) || atomic_read(&dsp->power_error)))
		err = -EIO;
	if (!err)
		err = READ_ONCE(dsp->primary_period_error);
	if (!err)
		err = n1x_adsp_primary_control(dsp, ADSP_PRIMARY_TASK, 0x0f, 0, ADSP_PROCESSING_TASK);
	if (!err && (READ_ONCE(dsp->ipc_poisoned) || atomic_read(&dsp->power_error)))
		err = -EIO;
	if (!err)
		err = READ_ONCE(dsp->primary_period_error);
	if (err) {
		dsp->primary_pcm_error = err;
		dsp->primary_task_error = err;
	} else {
		dsp->primary_running = true;
	}
unlock:
	mutex_unlock(&dsp->lock);
unlock_device:
	device_unlock(dev);
	if (endpoint)
		symbol_put(mt8901_afe_sram_endpoint);
	return err;
}

int n1x_adsp_primary_start(struct n1x_adsp_primary *primary)
{
	return n1x_adsp_primary_trigger(primary, true);
}
EXPORT_SYMBOL_GPL(n1x_adsp_primary_start);

int n1x_adsp_primary_stop(struct n1x_adsp_primary *primary)
{
	return n1x_adsp_primary_trigger(primary, false);
}
EXPORT_SYMBOL_GPL(n1x_adsp_primary_stop);

int n1x_adsp_primary_commit(struct n1x_adsp_primary *primary, u32 byte_offset)
{
	u8 descriptor[N1X_ADSP_PCM_BYTES];
	struct n1x_adsp *dsp;
	unsigned long flags;
	struct device *dev;
	int err;

	if (IS_ERR_OR_NULL(primary))
		return -EINVAL;
	dev = primary->dev;
	device_lock(dev);
	if (dev->driver != &n1x_adsp_driver.driver) {
		err = -ENODEV;
		goto unlock_device;
	}
	dsp = dev_get_drvdata(dev);
	err = mutex_lock_interruptible(&dsp->lock);
	if (err)
		goto unlock_device;
	if (dsp->sleep_prepared) {
		err = -EBUSY;
		goto unlock;
	}
	if (dsp->primary_owner != primary || !dsp->primary_task_active ||
	    !dsp->primary_pcm_configured || !dsp->primary_pcm_prepared || !dsp->dram) {
		err = -EINVAL;
		goto unlock;
	}
	spin_lock_irqsave(&dsp->ipc_lock, flags);
	if (dsp->primary_task_error)
		err = dsp->primary_task_error;
	else if (dsp->ipc_poisoned)
		err = dsp->ipc_error ?: -EPROTO;
	else if (atomic_read(&dsp->power_error))
		err = -EHOSTDOWN;
	else if (dsp->primary_period_error)
		err = dsp->primary_period_error;
	else if (!dsp->primary_period_enabled)
		err = -ENODATA;
	else if (dsp->primary_write_publications == U64_MAX)
		err = -EOVERFLOW;
	else
		err = n1x_adsp_pcm_producer_encode(descriptor, sizeof(descriptor),
						  &dsp->primary_host_pcm,
						  dsp->primary_read_address,
						  byte_offset, dsp->primary_write_counter);
	if (err)
		goto unlock_irq;
	/* Publish completed coherent sample writes before the new descriptor. */
	dma_wmb();
	memcpy(dsp->dram, descriptor, sizeof(descriptor));
	/* Make the descriptor visible before reporting the publication complete. */
	dma_wmb();
	dsp->primary_write_offset = byte_offset;
	dsp->primary_write_counter = dsp->primary_write_counter == 0x7fffffff ?
				     0 : dsp->primary_write_counter + 1;
	dsp->primary_write_publications++;
	if (atomic_read(&dsp->power_error)) {
		err = -EIO;
		dsp->primary_pcm_error = err;
		dsp->primary_task_error = err;
	}
unlock_irq:
	spin_unlock_irqrestore(&dsp->ipc_lock, flags);
unlock:
	mutex_unlock(&dsp->lock);
unlock_device:
	device_unlock(dev);
	return err;
}
EXPORT_SYMBOL_GPL(n1x_adsp_primary_commit);

int n1x_adsp_primary_set_period(struct n1x_adsp_primary *primary,
			       void (*period)(void *data,
					      const struct n1x_adsp_pcm_position *position,
					      int error), void *data)
{
	struct n1x_adsp *dsp;
	unsigned long flags;
	int err = 0;

	if (IS_ERR_OR_NULL(primary))
		return -EINVAL;
	dsp = primary->dsp;
	mutex_lock(&dsp->lock);
	if (dsp->primary_owner != primary) {
		err = -EINVAL;
		goto unlock;
	}
	spin_lock_irqsave(&dsp->ipc_lock, flags);
	if (period && dsp->primary_task_error)
		err = dsp->primary_task_error;
	else if (period && dsp->ipc_poisoned)
		err = dsp->ipc_error ?: -EPROTO;
	else if (period && atomic_read(&dsp->power_error))
		err = -EHOSTDOWN;
	else if (period && dsp->primary_period_error)
		err = dsp->primary_period_error;
	else if (period && dsp->primary_period)
		err = -EBUSY;
	else {
		dsp->primary_period = period;
		dsp->primary_period_data = period ? data : NULL;
	}
	spin_unlock_irqrestore(&dsp->ipc_lock, flags);
	if (!period)
		synchronize_irq(dsp->irq);
unlock:
	mutex_unlock(&dsp->lock);
	return err;
}
EXPORT_SYMBOL_GPL(n1x_adsp_primary_set_period);

int n1x_adsp_primary_position(struct n1x_adsp_primary *primary,
			     struct n1x_adsp_pcm_position *position)
{
	struct n1x_adsp *dsp;
	unsigned long flags;
	int err;

	if (IS_ERR_OR_NULL(primary) || !position)
		return -EINVAL;
	dsp = primary->dsp;
	spin_lock_irqsave(&dsp->ipc_lock, flags);
	if (dsp->ipc_poisoned)
		err = dsp->ipc_error ?: -EPROTO;
	else if (atomic_read(&dsp->power_error))
		err = -EHOSTDOWN;
	else if (dsp->primary_period_error)
		err = dsp->primary_period_error;
	else if (!dsp->primary_period_enabled)
		err = -ENODATA;
	else {
		*position = dsp->primary_position;
		err = 0;
	}
	spin_unlock_irqrestore(&dsp->ipc_lock, flags);
	return err;
}
EXPORT_SYMBOL_GPL(n1x_adsp_primary_position);

u32 n1x_adsp_primary_abi(void)
{
	return N1X_ADSP_PRIMARY_ABI;
}
EXPORT_SYMBOL_GPL(n1x_adsp_primary_abi);

module_platform_driver(n1x_adsp_driver);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("MT8901 DSP boot, IPC and playback services");
MODULE_VERSION("0.1.18");
MODULE_FIRMWARE("nvidia/n1x/hifi5-0-mt8901-signed.bin");
MODULE_FIRMWARE("nvidia/n1x/hifi5-1-mt8901-signed.bin");
MODULE_FIRMWARE("nvidia/n1x/hifi1-0-mt8901-signed.bin");
