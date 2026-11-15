// SPDX-License-Identifier: GPL-2.0-only
/* Deliberately leave an emulated, empty host suspended for hot-remove in QEMU. */
#include <linux/device.h>
#include <linux/dmi.h>
#include <linux/module.h>
#include <linux/pci.h>
#include "sdhci.h"
#include "sdhci-pci.h"

static bool run_test;
module_param(run_test, bool, 0400);

static int __init remove_test_init(void)
{
	struct pci_dev *pdev;
	struct sdhci_pci_chip *chip;
	struct sdhci_host *host;
	int ret = -ENODEV;

	if (!run_test || !dmi_match(DMI_SYS_VENDOR, "QEMU"))
		return -ENODEV;
	/* QEMU's emulated SDHCI, never a workstation's Genesys controller. */
	pdev = pci_get_device(0x1b36, 0x0007, NULL);
	if (!pdev)
		return -ENODEV;
	device_lock(&pdev->dev);
	if (!pdev->driver || strcmp(pdev->driver->name, "sdhci-pci"))
		goto unlock;
	chip = pci_get_drvdata(pdev);
	if (!chip || chip->num_slots != 1 || !chip->slots[0])
		goto unlock;
	host = chip->slots[0]->host;
	if (!host || host->mmc->card) {
		ret = -EBUSY;
		goto unlock;
	}
	ret = sdhci_suspend_host(host);
	if (!ret)
		pr_info("SDHCI_VM_SUSPENDED bdf=%s irq=%d\n", pci_name(pdev), host->irq);
unlock:
	device_unlock(&pdev->dev);
	pci_dev_put(pdev);
	return ret;
}
static void __exit remove_test_exit(void) { }
module_init(remove_test_init);
module_exit(remove_test_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("QEMU-only suspended SDHCI hot-removal regression");
