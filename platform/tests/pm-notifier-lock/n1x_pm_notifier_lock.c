// SPDX-License-Identifier: GPL-2.0-only
/* QEMU-only model of a write gate spanning PM PREPARE and POST. */
#include <linux/debug_locks.h>
#include <linux/dmi.h>
#include <linux/errno.h>
#include <linux/module.h>
#include <linux/rwsem.h>
#include <linux/suspend.h>
#include <linux/completion.h>
#include <linux/kthread.h>

static DECLARE_RWSEM(model_gate);
static bool run_test;
static bool gate_held;
static unsigned int prepares, posts;
module_param(run_test, bool, 0400);
MODULE_PARM_DESC(run_test, "Explicitly admit this model in a disposable QEMU guest");

#ifdef N1X_TEST_WORKER
/* notifier.inc is extracted from the patched vendor nv.c, not a rewrite. */
typedef int NV_STATUS;
typedef int nv_power_state_t;
#define NV_OK 0
#define NV_POWER_STATE_IN_STANDBY 1
#define NV_POWER_STATE_IN_HIBERNATE 2
#define NV_POWER_STATE_RUNNING 0
#define NV_DBG_ERRORS 0
#define nv_printf(level, ...) pr_info(__VA_ARGS__)
static int nv_procfs_pm_action_depth;
static bool fail_prepare, fail_resume, fail_thread, late_fail;
module_param(fail_prepare, bool, 0400);
module_param(fail_resume, bool, 0400);
module_param(fail_thread, bool, 0400);
module_param(late_fail, bool, 0400);

static NV_STATUS nv_set_system_power_state(nv_power_state_t state, int depth)
{
	if (state != NV_POWER_STATE_RUNNING) {
		down_write(&model_gate);
		prepares++;
		if (fail_prepare) {
			up_write(&model_gate);
			return 7;
		}
		gate_held = true;
		return NV_OK;
	}
	if (WARN_ON(!gate_held))
		return 9;
	gate_held = false;
	posts++;
	up_write(&model_gate);
	return fail_resume ? 8 : NV_OK;
}

static struct task_struct *model_run(int (*fn)(void *), void *data, const char *name)
{
	if (fail_thread)
		return ERR_PTR(-ENOMEM);
	return kthread_run(fn, data, "%s", name);
}
#undef kthread_run
#define kthread_run model_run
#include "notifier.inc"

static int model_notify(struct notifier_block *nb, unsigned long event, void *data)
{
	int rc = nv_pm_notifier(nb, event, data);

	pr_info("PM_OWNER_MODEL event=%lu rc=%d prepares=%u posts=%u held=%d task=%d refs=%d debug_locks=%d\n",
		event, rc, prepares, posts, gate_held, !!nv_pm_context.task,
		module_refcount(THIS_MODULE), debug_locks);
	return rc;
}

static int model_late_fail(struct notifier_block *nb, unsigned long event, void *data)
{
	return event == PM_SUSPEND_PREPARE && late_fail ? NOTIFY_BAD : NOTIFY_DONE;
}

static struct notifier_block late_nb = {
	.notifier_call = model_late_fail,
	.priority = -1,
};
#else

static bool retain_gate = true;
module_param(retain_gate, bool, 0400);
MODULE_PARM_DESC(retain_gate, "Hold a writer across callbacks; false is a scoped-lock control");

static int model_notify(struct notifier_block *nb, unsigned long event, void *data)
{
	if (event == PM_SUSPEND_PREPARE) {
		down_write(&model_gate);
		prepares++;
		if (retain_gate)
			gate_held = true;
		else
			up_write(&model_gate);
	} else if (event == PM_POST_SUSPEND) {
		if (gate_held) {
			gate_held = false;
			up_write(&model_gate);
		}
		posts++;
		pr_info("PM_NOTIFIER_MODEL retain=%d prepares=%u posts=%u debug_locks=%d\n",
			retain_gate, prepares, posts, debug_locks);
	}
	return NOTIFY_OK;
}
#endif

static struct notifier_block model_nb = {
	.notifier_call = model_notify,
};

static int __init model_init(void)
{
	int rc;

	if (!run_test || !dmi_match(DMI_SYS_VENDOR, "QEMU"))
		return -ENODEV;
	if (!IS_ENABLED(CONFIG_LOCKDEP) || !debug_locks)
		return -EUCLEAN;
	rc = register_pm_notifier(&model_nb);
#ifdef N1X_TEST_WORKER
	if (!rc) {
		rc = register_pm_notifier(&late_nb);
		if (rc)
			unregister_pm_notifier(&model_nb);
	}
#endif
	return rc;
}

static void __exit model_exit(void)
{
#ifdef N1X_TEST_WORKER
	unregister_pm_notifier(&late_nb);
#endif
	unregister_pm_notifier(&model_nb);
}

module_init(model_init);
module_exit(model_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("QEMU-only PM notifier cross-callback lock-order model");
