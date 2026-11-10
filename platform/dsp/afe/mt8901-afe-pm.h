/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef MT8901_AFE_PM_H
#define MT8901_AFE_PM_H

static int mt8901_afe_pm_prepare(struct device *dev)
{
	return mt8901_afe_sram_pm_prepare(dev_get_drvdata(dev));
}

static void mt8901_afe_pm_complete(struct device *dev)
{
	mt8901_afe_sram_pm_complete(dev_get_drvdata(dev));
}

static int mt8901_afe_pm_resume(struct device *dev)
{
	int ret = pm_runtime_force_resume(dev);

	if (!ret)
		mt8901_afe_sram_pm_restore(dev_get_drvdata(dev));
	return ret;
}

static int mt8901_afe_pm_suspend(struct device *dev)
{
	int ret;

	ret = mt8901_afe_sram_pm_save(dev_get_drvdata(dev));
	if (ret)
		return ret;
	ret = pm_runtime_force_suspend(dev);
	/* A device whose suspend fails is not resumed by the PM core. Restore
	 * its SRAM only after successful force-resume; otherwise keep the saved
	 * state and DSP votes so consumers cannot resume against an off AFE.
	 */
	if (ret)
		mt8901_afe_pm_resume(dev);
	return ret;
}
#endif
